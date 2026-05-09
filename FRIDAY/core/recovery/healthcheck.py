from __future__ import annotations

import asyncio

from core.events.bus import EventBus
from core.events.event_types import EventType
from core.events.models import Event
from core.workers.base_worker import BaseWorker


class HealthcheckWorker(BaseWorker):
    def __init__(self, event_bus: EventBus, interval_seconds: float = 30.0) -> None:
        super().__init__("healthcheck", event_bus)
        self.interval_seconds = interval_seconds

    async def work(self) -> None:
        while not self.should_stop:
            self.heartbeat("publishing_healthcheck")
            await self.event_bus.publish(Event.create(EventType.HEALTHCHECK, {}, self.name))
            await asyncio.sleep(self.interval_seconds)
