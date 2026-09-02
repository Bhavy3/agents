from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from core.config.constants import (
    DEFAULT_EVENT_HANDLER_TIMEOUT_SECONDS,
    DEFAULT_EVENT_MAX_AGE_SECONDS,
    DEFAULT_QUEUE_HIGH_WATERMARK_RATIO,
)
from core.events.event_types import EventType
from core.events.models import Event, EventPriority, EventState
from core.exceptions import TimeoutError as FridayTimeoutError
from core.logging.logger import get_logger
from core.metrics.metrics import RuntimeMetrics

EventHandler = Callable[[Event], Awaitable[None]]


@dataclass(slots=True)
class EventBus:
    max_queue_size: int = 1000
    metrics: RuntimeMetrics | None = None
    event_max_age_seconds: float = DEFAULT_EVENT_MAX_AGE_SECONDS
    handler_timeout_seconds: float = DEFAULT_EVENT_HANDLER_TIMEOUT_SECONDS
    high_watermark_ratio: float = DEFAULT_QUEUE_HIGH_WATERMARK_RATIO
    _queue: asyncio.Queue[Event] = field(init=False)
    _subscribers: dict[EventType, list[EventHandler]] = field(default_factory=dict)
    _wildcard_subscribers: list[EventHandler] = field(default_factory=list)
    _dispatcher_task: asyncio.Task[None] | None = None
    _running: bool = False
    _publishing_notification: bool = False
    _logger: logging.Logger = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._queue = asyncio.Queue(maxsize=self.max_queue_size)
        self._logger = get_logger("events.bus")

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._dispatcher_task = asyncio.create_task(
            self._dispatch_loop(),
            name="event-bus-dispatcher",
        )
        self._logger.info("event_bus_started")

    async def stop(self) -> None:
        self._running = False
        if self._dispatcher_task is not None:
            self._dispatcher_task.cancel()
            try:
                await self._dispatcher_task
            except asyncio.CancelledError:
                pass
        self._logger.info("event_bus_stopped")

    def subscribe(self, event_type: EventType, handler: EventHandler) -> None:
        self._subscribers.setdefault(event_type, []).append(handler)

    def subscribe_all(self, handler: EventHandler) -> None:
        self._wildcard_subscribers.append(handler)

    async def publish(self, event: object) -> None:
        if not self._running:
            raise RuntimeError("EventBus must be started before publishing events.")
        if not self._validate_event_boundary(event):
            return
        if self._should_drop_for_backpressure(event):
            self._record_backpressure_drop(event)
            return
        try:
            await asyncio.wait_for(
                self._queue.put(event),
                timeout=self.handler_timeout_seconds,
            )
            event.transition(EventState.QUEUED)
        except (TimeoutError, asyncio.TimeoutError):
            self._record_backpressure_drop(event)

    async def publish_raw_for_validation(self, raw_event: object) -> None:
        if not self._running:
            raise RuntimeError("EventBus must be started before publishing events.")
        await self.publish(raw_event)

    async def publish_nowait_safe(self, event: object) -> bool:
        if not self._running:
            return False
        if not self._validate_event_boundary(event):
            return False
        if self._should_drop_for_backpressure(event):
            self._record_backpressure_drop(event)
            return False
        try:
            self._queue.put_nowait(event)
            event.transition(EventState.QUEUED)
        except asyncio.QueueFull:
            if self.metrics is not None:
                self.metrics.record_dropped_event()
            self._logger.error(
                "event_queue_full",
                extra={"event_id": event.event_id, "event_type": event.event_type.value},
            )
            return False
        return True

    async def _dispatch_loop(self) -> None:
        while self._running:
            event = await self._queue.get()
            if self.metrics is not None:
                self.metrics.queue_depth = self._queue.qsize()
            event_age_seconds = (datetime.now(UTC) - event.created_at).total_seconds()
            if event_age_seconds > self.event_max_age_seconds:
                if self.metrics is not None:
                    self.metrics.record_dropped_event()
                self._logger.warning(
                    "stale_event_dropped",
                    extra={
                        "event_id": event.event_id,
                        "event_type": event.event_type.value,
                        "event_age_seconds": round(event_age_seconds, 3),
                    },
                )
                event.transition(EventState.DROPPED)
                self._queue.task_done()
                continue
            
            event.transition(EventState.PROCESSING)
            handlers = [
                *self._subscribers.get(event.event_type, []),
                *self._wildcard_subscribers,
            ]
            started_at = time.perf_counter()
            event_failed = False
            for handler in handlers:
                try:
                    await asyncio.wait_for(handler(event), timeout=self.handler_timeout_seconds)
                except (TimeoutError, asyncio.TimeoutError):
                    event_failed = True
                    self._logger.exception(
                        "event_handler_timed_out",
                        extra={
                            "event_id": event.event_id,
                            "correlation_id": event.correlation_id,
                            "event_type": event.event_type.value,
                            "timeout_seconds": self.handler_timeout_seconds,
                        },
                    )
                except asyncio.CancelledError:
                    event.transition(EventState.FAILED)
                    self._queue.task_done()
                    raise
                except Exception:
                    event_failed = True
                    self._logger.exception(
                        "event_handler_failed",
                        extra={
                            "event_id": event.event_id,
                            "correlation_id": event.correlation_id,
                            "event_type": event.event_type.value,
                        },
                    )
            duration_seconds = time.perf_counter() - started_at
            if self.metrics is not None:
                self.metrics.record_processed_event(duration_seconds)
                if event_failed:
                    self.metrics.record_failed_event()
            
            if event_failed:
                event.transition(EventState.FAILED)
            else:
                event.transition(EventState.COMPLETED)
                
            self._queue.task_done()
            if self.metrics is not None:
                self.metrics.queue_depth = self._queue.qsize()

    async def drain(self) -> None:
        await self._queue.join()

    @property
    def queue_depth(self) -> int:
        return self._queue.qsize()

    @property
    def queue_utilization(self) -> float:
        if self.max_queue_size <= 0:
            return 0.0
        return self._queue.qsize() / self.max_queue_size

    def _should_drop_for_backpressure(self, event: Event) -> bool:
        if event.priority <= EventPriority.HIGH:
            return False
        return self.queue_utilization >= self.high_watermark_ratio

    def _record_backpressure_drop(self, event: Event) -> None:
        if self.metrics is not None:
            self.metrics.record_dropped_event()
            self.metrics.queue_depth = self._queue.qsize()
        event.transition(EventState.DROPPED)
        self._logger.warning(
            "backpressure_event_dropped",
            extra={
                "event_id": event.event_id,
                "event_type": event.event_type.value,
                "priority": int(event.priority),
                "queue_depth": self._queue.qsize(),
                "queue_utilization": round(self.queue_utilization, 3),
            },
        )
        if event.event_type == EventType.BACKPRESSURE_APPLIED:
            return
        # Re-entrancy guard: don't recursively enqueue notifications
        if self._publishing_notification:
            return
        self._publishing_notification = True
        try:
            backpressure_event = Event.create(
                EventType.BACKPRESSURE_APPLIED,
                {
                    "dropped_event_id": event.event_id,
                    "dropped_event_type": event.event_type.value,
                    "queue_depth": self._queue.qsize(),
                    "queue_utilization": self.queue_utilization,
                },
                "event_bus",
                priority=EventPriority.CRITICAL,
            )
            self._queue.put_nowait(backpressure_event)
        except asyncio.QueueFull:
            self._logger.error("backpressure_notice_dropped_queue_full")
        finally:
            self._publishing_notification = False

    def _validate_event_boundary(self, candidate: object) -> bool:
        from core.events.contracts import validate_event_payload
        from core.exceptions import ValidationError

        if not isinstance(candidate, Event):
            self._drop_malformed_event(
                reason="invalid_event_object",
                details={"event_class": type(candidate).__name__},
            )
            return False
        if not isinstance(candidate.event_type, EventType):
            self._drop_malformed_event(
                reason="invalid_event_type",
                details={
                    "event_id": candidate.event_id,
                    "event_type": str(candidate.event_type),
                },
            )
            return False
        if not isinstance(candidate.payload, dict):
            self._drop_malformed_event(
                reason="invalid_event_payload_not_dict",
                details={
                    "event_id": candidate.event_id,
                    "event_type": candidate.event_type.value,
                    "payload_class": type(candidate.payload).__name__,
                },
            )
            return False
        
        try:
            validate_event_payload(candidate.event_type, candidate.payload)
        except ValidationError as e:
            self._drop_malformed_event(
                reason="contract_violation",
                details={
                    "event_id": candidate.event_id,
                    "event_type": candidate.event_type.value,
                    "error": str(e),
                },
            )
            return False

        if not isinstance(candidate.priority, EventPriority):
            self._drop_malformed_event(
                reason="invalid_event_priority",
                details={
                    "event_id": candidate.event_id,
                    "event_type": candidate.event_type.value,
                    "priority": str(candidate.priority),
                },
            )
            return False
        return True

    def _drop_malformed_event(self, reason: str, details: dict[str, object]) -> None:
        if self.metrics is not None:
            self.metrics.record_dropped_event()
            self.metrics.queue_depth = self._queue.qsize()
        self._logger.debug(
            "malformed_event_dropped",
            extra={"reason": reason, **details},
        )
        # Re-entrancy guard: if we're already publishing a notification event,
        # don't enqueue another one — that creates an infinite cascade.
        if self._publishing_notification:
            return
        self._publishing_notification = True
        try:
            malformed_event = Event.create(
                EventType.MALFORMED_EVENT_DROPPED,
                {"reason": reason, "details": details},
                "event_bus",
                priority=EventPriority.CRITICAL,
            )
            self._queue.put_nowait(malformed_event)
        except asyncio.QueueFull:
            self._logger.error(
                "malformed_event_notice_dropped_queue_full",
                extra={"reason": reason},
            )
        finally:
            self._publishing_notification = False
