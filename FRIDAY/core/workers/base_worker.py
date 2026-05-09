from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod

from core.events.bus import EventBus
from core.events.event_types import EventType
from core.events.models import Event
from core.logging.logger import get_logger
from core.workers.health import WorkerHealth, WorkerState


class BaseWorker(ABC):
    def __init__(self, name: str, event_bus: EventBus) -> None:
        self.name = name
        self.event_bus = event_bus
        self._stop_event = asyncio.Event()
        self.logger = get_logger(f"workers.{name}")
        self.health = WorkerHealth(name=name)
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self.run(), name=f"worker-{self.name}")

    async def run(self) -> None:
        self._stop_event.clear()
        self.health.mark_starting()
        await self.event_bus.publish(
            Event.create(EventType.WORKER_STARTED, {"worker": self.name}, self.name)
        )
        try:
            self.health.mark_alive("running")
            await self.work()
        except Exception:
            self.health.mark_failed()
            raise
        finally:
            if self.health.state not in {WorkerState.FAILED, WorkerState.QUARANTINED, WorkerState.DISABLED}:
                self.health.mark_stopped()
            await self.event_bus.publish(
                Event.create(EventType.WORKER_STOPPED, {"worker": self.name}, self.name)
            )

    async def stop(self) -> None:
        self._stop_event.set()

    @property
    def should_stop(self) -> bool:
        return self._stop_event.is_set()

    def heartbeat(self, task: str = "running") -> None:
        self.health.mark_alive(task)

    @abstractmethod
    async def work(self) -> None:
        raise NotImplementedError
