from __future__ import annotations

import asyncio
import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime

from core.config.constants import (
    DEFAULT_WORKER_RESTART_DELAY_SECONDS,
    DEFAULT_WORKER_HEARTBEAT_TIMEOUT_SECONDS,
    MAX_WORKER_RESTART_DELAY_SECONDS,
    DEFAULT_MAX_RESTARTS_PER_MINUTE,
)
from core.events.bus import EventBus
from core.events.event_types import EventType
from core.events.models import Event, EventPriority
from core.logging.logger import get_logger
from core.metrics.metrics import RuntimeMetrics
from core.workers.base_worker import BaseWorker
from core.workers.health import WorkerState


@dataclass(slots=True)
class WorkerSupervisor:
    event_bus: EventBus
    workers: list[BaseWorker]
    metrics: RuntimeMetrics | None = None
    heartbeat_timeout_seconds: float = DEFAULT_WORKER_HEARTBEAT_TIMEOUT_SECONDS
    max_restarts_per_minute: int = DEFAULT_MAX_RESTARTS_PER_MINUTE
    max_total_restarts: int = 15
    max_total_restarts_window_seconds: float = 600.0
    _tasks: dict[str, asyncio.Task[None]] = field(default_factory=dict)
    _worker_tasks: dict[str, asyncio.Task[None]] = field(default_factory=dict)
    _worker_task_generations: dict[str, int] = field(default_factory=dict)
    _restart_windows: dict[str, deque[datetime]] = field(default_factory=dict)
    _total_restart_windows: dict[str, deque[datetime]] = field(default_factory=dict)
    _running: bool = False
    logger: logging.Logger = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.logger = get_logger("workers.supervisor")

    async def start(self) -> None:
        self._running = True
        if self.metrics is not None:
            self.metrics.active_workers = len(self.workers)
        for worker in self.workers:
            self._restart_windows[worker.name] = deque()
            self._total_restart_windows[worker.name] = deque()
            self._total_restart_windows[worker.name] = deque()
            self.logger.info(
                "worker_supervision_scheduled",
                extra={"worker": worker.name, "state": worker.health.state.value},
            )
            self._tasks[worker.name] = asyncio.create_task(
                self._supervise(worker),
                name=f"supervisor-{worker.name}",
            )
        self.logger.info("worker_supervisor_started")

    async def stop(self) -> None:
        self._running = False
        for worker in self.workers:
            await worker.stop()
        for task in self._tasks.values():
            task.cancel()
        await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        self._tasks.clear()
        self._worker_tasks.clear()
        if self.metrics is not None:
            self.metrics.active_workers = 0
        self.logger.info("worker_supervisor_stopped")

    async def _supervise(self, worker: BaseWorker) -> None:
        restart_delay = DEFAULT_WORKER_RESTART_DELAY_SECONDS
        while self._running:
            if worker.health.state in {WorkerState.QUARANTINED, WorkerState.DISABLED}:
                self.logger.warning(
                    "worker_supervision_skipped_isolated",
                    extra={"worker": worker.name, "state": worker.health.state.value},
                )
                break
            try:
                generation = self._worker_task_generations.get(worker.name, 0) + 1
                self._worker_task_generations[worker.name] = generation
                self.logger.info(
                    "worker_task_launching",
                    extra={
                        "worker": worker.name,
                        "restart_count": worker.health.restart_count,
                        "worker_task_generation": generation,
                        "previous_state": worker.health.state.value,
                    },
                )
                worker_task = asyncio.create_task(worker.run(), name=f"worker-{worker.name}-{generation}")
                self._worker_tasks[worker.name] = worker_task

                error: Exception | None = None
                poll_interval = max(0.01, min(1.0, self.heartbeat_timeout_seconds / 3))
                while self._running and not worker_task.done():
                    done, _ = await asyncio.wait({worker_task}, timeout=poll_interval)
                    if done:
                        break
                    last_heartbeat = worker.health.last_heartbeat
                    if last_heartbeat is None:
                        continue
                    heartbeat_age = (datetime.now(UTC) - last_heartbeat).total_seconds()
                    if heartbeat_age <= self.heartbeat_timeout_seconds:
                        continue
                    worker.health.mark_failed()
                    error = RuntimeError(f"worker heartbeat timeout: {worker.name}")
                    self.logger.error(
                        "worker_heartbeat_timeout_detected",
                        extra={
                            "worker": worker.name,
                            "heartbeat_age_seconds": round(heartbeat_age, 3),
                        },
                    )
                    worker_task.cancel()
                    try:
                        await asyncio.wait_for(asyncio.gather(worker_task, return_exceptions=True), timeout=5.0)
                    except asyncio.TimeoutError:
                        self.logger.error(
                            "worker_cancel_timeout",
                            extra={"worker": worker.name, "timeout_seconds": 5.0},
                        )
                    break

                if error is None:
                    try:
                        await worker_task
                    except Exception as exc:
                        error = exc
                    except asyncio.CancelledError:
                        error = RuntimeError("worker task was cancelled")

                if error is None and self._running and not worker.should_stop:
                    worker.health.mark_failed()
                    error = RuntimeError("worker exited unexpectedly")
                    self.logger.warning(
                        "worker_completed_unexpectedly",
                        extra={"worker": worker.name, "state": worker.health.state.value},
                    )
            except asyncio.CancelledError:
                task = self._worker_tasks.pop(worker.name, None)
                if task is not None:
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                raise
            finally:
                self._worker_tasks.pop(worker.name, None)

            if not self._running or worker.should_stop:
                break

            if error is None:
                error = RuntimeError("unknown worker failure")

            self.logger.error(
                "worker_failed",
                extra={
                    "worker": worker.name,
                    "state": worker.health.state.value,
                    "restart_count": worker.health.restart_count,
                    "error": str(error),
                },
                exc_info=(type(error), error, error.__traceback__),
            )
            await self.event_bus.publish(
                Event.create(
                    EventType.WORKER_FAILED,
                    {"worker": worker.name, "error": str(error)},
                    "supervisor",
                )
            )

            worker.health.mark_restarting()
            restart_allowed = self._register_restart_attempt(worker)
            if not restart_allowed:
                worker.health.mark_quarantined()
                self.logger.error(
                    "worker_quarantined_restart_loop",
                    extra={
                        "worker": worker.name,
                        "max_restarts_per_minute": self.max_restarts_per_minute,
                        "restart_count": worker.health.restart_count,
                        "state": worker.health.state.value,
                    },
                )
                await self.event_bus.publish(
                    Event.create(
                        EventType.CRITICAL_WORKER_FAILURE,
                        {
                            "worker": worker.name,
                            "error": "restart loop prevented",
                            "quarantined": True,
                            "restart_count": worker.health.restart_count,
                        },
                        "supervisor",
                        priority=EventPriority.CRITICAL,
                    )
                )
                break

            self.logger.warning(
                "worker_restart_scheduled",
                extra={
                    "worker": worker.name,
                    "delay_seconds": restart_delay,
                    "restart_count": worker.health.restart_count,
                    "state": worker.health.state.value,
                },
            )
            if self.metrics is not None:
                self.metrics.record_restart()
            await asyncio.sleep(restart_delay)
            await self.event_bus.publish(
                Event.create(
                    EventType.WORKER_RESTARTED,
                    {
                        "worker": worker.name,
                        "delay_seconds": restart_delay,
                        "restart_count": worker.health.restart_count,
                    },
                    "supervisor",
                )
            )
            restart_delay = min(restart_delay * 2, MAX_WORKER_RESTART_DELAY_SECONDS)

    def _register_restart_attempt(self, worker: BaseWorker) -> bool:
        now = datetime.now(UTC)
        
        # 1. Check short-term fast crashes (per minute)
        restart_window = self._restart_windows.setdefault(worker.name, deque())
        while restart_window and (now - restart_window[0]).total_seconds() > 60.0:
            restart_window.popleft()
        restart_window.append(now)
        allowed_short = len(restart_window) <= self.max_restarts_per_minute
        
        # 2. Check long-term cumulative slow crashes (over the longer window)
        total_window = self._total_restart_windows.setdefault(worker.name, deque())
        while total_window and (now - total_window[0]).total_seconds() > self.max_total_restarts_window_seconds:
            total_window.popleft()
        total_window.append(now)
        allowed_long = len(total_window) <= self.max_total_restarts
        
        allowed = allowed_short and allowed_long
        
        self.logger.info(
            "worker_restart_attempt_recorded",
            extra={
                "worker": worker.name,
                "attempts_in_minute": len(restart_window),
                "max_restarts_per_minute": self.max_restarts_per_minute,
                "attempts_in_total_window": len(total_window),
                "max_total_restarts": self.max_total_restarts,
                "total_window_seconds": self.max_total_restarts_window_seconds,
                "restart_allowed": allowed,
                "reason_denied": "fast_crash_limit" if not allowed_short else ("slow_crash_limit" if not allowed_long else None)
            },
        )
        return allowed

    def health_snapshot(self) -> list[dict[str, object]]:
        return [
            {
                "name": worker.health.name,
                "alive": worker.health.alive,
                "state": worker.health.state.value,
                "last_heartbeat": worker.health.last_heartbeat,
                "uptime_seconds": round(worker.health.uptime_seconds, 3),
                "restart_count": worker.health.restart_count,
                "current_task": worker.health.current_task,
            }
            for worker in self.workers
        ]

    def current_worker_task_generation(self, worker_name: str) -> int:
        return self._worker_task_generations.get(worker_name, 0)

    def is_supervising(self, worker_name: str) -> bool:
        task = self._tasks.get(worker_name)
        return task is not None and not task.done()

    def restart_worker(self, worker_name: str) -> bool:
        for worker in self.workers:
            if worker.name == worker_name:
                worker.health.mark_restarting()
                task = self._worker_tasks.get(worker.name)
                if task:
                    task.cancel()
                return True
        return False

    def quarantine_worker(self, worker_name: str) -> bool:
        for worker in self.workers:
            if worker.name == worker_name:
                worker.health.mark_quarantined()
                task = self._worker_tasks.get(worker.name)
                if task:
                    task.cancel()
                return True
        return False

