from __future__ import annotations

from collections import defaultdict

from core.events.bus import EventBus
from core.events.event_types import EventType
from core.events.models import Event
from core.logging.logger import get_logger


class RecoveryManager:
    def __init__(self, event_bus: EventBus) -> None:
        self.event_bus = event_bus
        self._notified_failures: set[str] = set()
        self._failure_counts: defaultdict[str, int] = defaultdict(int)
        self.logger = get_logger("recovery.manager")

    async def start(self) -> None:
        self.event_bus.subscribe(EventType.WORKER_FAILED, self.handle_worker_failed)
        self.event_bus.subscribe(EventType.CRITICAL_WORKER_FAILURE, self.handle_critical_worker_failure)
        self.event_bus.subscribe(EventType.ERROR_OCCURRED, self.handle_error)
        self.logger.info("recovery_manager_started")

    async def handle_worker_failed(self, event: Event) -> None:
        worker = str(event.payload.get("worker", "unknown"))
        self._failure_counts[worker] += 1
        self.logger.warning(
            "worker_failure_recorded",
            extra={"worker": worker, "failure_count": self._failure_counts[worker]},
        )
        if worker not in self._notified_failures:
            self._notified_failures.add(worker)
            await self.event_bus.publish(
                Event.create(
                    EventType.RESPONSE_READY,
                    {"text": "Sorry, I hit a small issue but I’m still here."},
                    "recovery_manager",
                    event.correlation_id,
                )
            )

    async def handle_error(self, event: Event) -> None:
        self.logger.error("error_event_recorded", extra={"payload": event.payload})

    async def handle_critical_worker_failure(self, event: Event) -> None:
        worker = str(event.payload.get("worker", "unknown"))
        self.logger.critical(
            "critical_worker_failure",
            extra={"worker": worker, "payload": event.payload},
        )
        await self.event_bus.publish(
            Event.create(
                EventType.RESPONSE_READY,
                {"text": f"A worker was isolated after repeated failures: {worker}. Runtime is still alive."},
                "recovery_manager",
                event.correlation_id,
            )
        )
