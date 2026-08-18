import asyncio
import logging
from enum import IntEnum
from typing import Optional
from core.events.bus import EventBus
from core.events.event_types import EventType
from core.events.models import Event

class AttentionPriority(IntEnum):
    CRITICAL_INTERRUPTION = 100
    USER_SPEECH = 90
    ACTIVE_TOOL = 80
    ACTIVE_WORKFLOW = 70
    TTS_PLAYBACK = 60
    VISION_UPDATE = 40
    MEMORY_REFRESH = 30
    BACKGROUND = 10

class AttentionManager:
    """
    Central authority for conversational focus and subsystem attention priority.
    """
    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus
        self.logger = logging.getLogger("cognition.attention")
        self._current_owner: Optional[str] = None
        self._current_priority: AttentionPriority = AttentionPriority.BACKGROUND
        self._lock = asyncio.Lock()

    async def acquire_attention(self, owner: str, priority: AttentionPriority) -> bool:
        async with self._lock:
            if priority >= self._current_priority or self._current_owner is None:
                self._current_owner = owner
                self._current_priority = priority
                
                await self.event_bus.publish(Event.create(
                    EventType.STATE_UPDATED,
                    {"reason": "attention_ownership_changed", "owner": owner, "priority": priority.name},
                    "attention_manager"
                ))
                return True
            return False

    async def release_attention(self, owner: str):
        async with self._lock:
            if self._current_owner == owner:
                self._current_owner = None
                self._current_priority = AttentionPriority.BACKGROUND
                
                await self.event_bus.publish(Event.create(
                    EventType.STATE_UPDATED,
                    {"reason": "attention_ownership_changed", "owner": "idle", "priority": "BACKGROUND"},
                    "attention_manager"
                ))

    def get_owner(self) -> Optional[str]:
        return self._current_owner

    def get_priority(self) -> AttentionPriority:
        return self._current_priority
