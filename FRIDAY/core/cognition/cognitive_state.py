import asyncio
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Optional
from core.events.bus import EventBus
from core.events.event_types import EventType
from core.events.models import Event

class TurnState(StrEnum):
    IDLE = "IDLE"
    LISTENING = "LISTENING"
    THINKING = "THINKING"
    RESPONDING = "RESPONDING"
    INTERRUPTED = "INTERRUPTED"
    YIELDING = "YIELDING"

@dataclass
class CognitiveState:
    active_turn_id: Optional[str] = None
    active_speaker: Optional[str] = None
    turn_state: TurnState = TurnState.IDLE
    assistant_busy: bool = False
    speaking: bool = False
    listening: bool = False
    active_workflow_id: Optional[str] = None
    interruption_owner: Optional[str] = None
    attention_target: Optional[str] = None
    last_activity_ts: float = field(default_factory=time.time)

class CognitiveStateEngine:
    """
    Single source of truth for the cognitive state of FRIDAY.
    Thread-safe and uses locks for atomic updates.
    """
    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus
        self._state = CognitiveState()
        self._lock = asyncio.Lock()

    async def get_state(self) -> CognitiveState:
        async with self._lock:
            # Return a copy to prevent external mutation
            return CognitiveState(**self._state.__dict__)

    async def update_state(self, **kwargs: Any) -> CognitiveState:
        async with self._lock:
            for key, value in kwargs.items():
                if hasattr(self._state, key):
                    # Validation rules
                    if key == "active_speaker" and value is not None:
                        if self._state.active_speaker is not None and self._state.active_speaker != value:
                            # Already has an active speaker
                            pass # We'll allow it for now but maybe log it
                    
                    setattr(self._state, key, value)
            
            self._state.last_activity_ts = time.time()
            
            # Publish update
            await self.event_bus.publish(Event.create(
                EventType.STATE_UPDATED,
                {"reason": "cognitive_state_updated", **self._state.__dict__},
                "cognitive_engine"
            ))
            
            return CognitiveState(**self._state.__dict__)

    async def acquire_turn(self, turn_id: str) -> bool:
        """Atomic turn acquisition. Prevents duplicate responses."""
        async with self._lock:
            if self._state.turn_state == TurnState.RESPONDING:
                return False
            
            self._state.active_turn_id = turn_id
            self._state.turn_state = TurnState.THINKING
            self._state.last_activity_ts = time.time()
            
            await self.event_bus.publish(Event.create(
                EventType.STATE_UPDATED,
                {"reason": "turn_ownership_acquired", "turn_id": turn_id},
                "cognitive_engine"
            ))
            return True

    async def release_turn(self, turn_id: str):
        """Atomic turn release."""
        async with self._lock:
            if self._state.active_turn_id == turn_id:
                self._state.active_turn_id = None
                self._state.turn_state = TurnState.IDLE
                self._state.last_activity_ts = time.time()
                
                await self.event_bus.publish(Event.create(
                    EventType.STATE_UPDATED,
                    {"reason": "turn_ownership_released", "turn_id": turn_id},
                    "cognitive_engine"
                ))

    async def set_turn_state(self, state: TurnState):
        """Update the turn state (e.g. to RESPONDING)."""
        async with self._lock:
            self._state.turn_state = state
            self._state.last_activity_ts = time.time()

    async def reset_interruption(self):
        async with self._lock:
            self._state.interruption_owner = None
