from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from core.events.bus import EventBus
from core.workers.base_worker import BaseWorker

WorkerFactory = Callable[[EventBus], BaseWorker]


@dataclass(slots=True)
class WorkerRegistry:
    _factories: dict[str, WorkerFactory] = field(default_factory=dict)

    def register(self, name: str, factory: WorkerFactory) -> None:
        if name in self._factories:
            raise ValueError(f"Worker already registered: {name}")
        self._factories[name] = factory

    def create_all(self, event_bus: EventBus) -> list[BaseWorker]:
        return [factory(event_bus) for factory in self._factories.values()]
