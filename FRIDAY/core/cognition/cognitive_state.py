import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Optional
from core.events.bus import EventBus
from core.events.event_types import EventType
from core.events.models import Event

logger = logging.getLogger("core.cognition.cognitive_state")

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
        self.current_tone: str = "curious"  # default

    async def get_state(self) -> CognitiveState:
        async with self._lock:
            # Return a copy to prevent external mutation
            return CognitiveState(**self._state.__dict__)

    async def update_state(self, **kwargs: Any) -> CognitiveState:
        requested = dict(kwargs)
        # Speaking and listening are mutually exclusive ownership states.  Keep
        # that invariant at the shared-state boundary so every caller gets the
        # same result, including legacy event handlers.
        if requested.get("speaking") is True:
            requested["listening"] = False
        elif requested.get("listening") is True:
            requested["speaking"] = False

        async with self._lock:
            changed = False
            for key, value in requested.items():
                if hasattr(self._state, key):
                    # Validation rules
                    if key == "active_speaker" and value is not None:
                        if self._state.active_speaker is not None and self._state.active_speaker != value:
                            # Already has an active speaker
                            pass # We'll allow it for now but maybe log it
                    
                    if getattr(self._state, key) != value:
                        setattr(self._state, key, value)
                        changed = True

            if not changed:
                return CognitiveState(**self._state.__dict__)

            self._state.last_activity_ts = time.time()
            state = CognitiveState(**self._state.__dict__)

        # Never await the event bus while holding the state lock.  The bus may
        # dispatch STATE_UPDATED to a handler which needs to read this engine;
        # publishing after the lock is released prevents that cycle from
        # blocking the dispatcher.
        await self._publish_state_update("cognitive_state_updated", state)
        return state

    async def acquire_turn(self, turn_id: str) -> bool:
        """Atomic turn acquisition. Prevents duplicate responses."""
        async with self._lock:
            if self._state.turn_state == TurnState.RESPONDING:
                return False
            
            self._state.active_turn_id = turn_id
            self._state.turn_state = TurnState.THINKING
            self._state.last_activity_ts = time.time()
            state = CognitiveState(**self._state.__dict__)

        await self._publish_state_update(
            "turn_ownership_acquired", state, turn_id=turn_id
        )
        return True

    async def release_turn(self, turn_id: str):
        """Atomic turn release."""
        async with self._lock:
            if self._state.active_turn_id == turn_id:
                self._state.active_turn_id = None
                self._state.turn_state = TurnState.IDLE
                self._state.last_activity_ts = time.time()
                state = CognitiveState(**self._state.__dict__)
            else:
                return False

        await self._publish_state_update(
            "turn_ownership_released", state, turn_id=turn_id
        )
        return True

    async def set_turn_state(self, state: TurnState):
        """Update the turn state (e.g. to RESPONDING)."""
        async with self._lock:
            if self._state.turn_state == state:
                return
            self._state.turn_state = state
            self._state.last_activity_ts = time.time()

    async def apply_event(self, event: Event) -> bool:
        """Apply a canonical or legacy lifecycle event idempotently.

        Both the orchestrator and the cognition worker observe the event bus.
        They may therefore see the same lifecycle event from different paths;
        these transitions make the second application a no-op rather than a
        competing state mutation.
        """
        event_type = event.event_type
        payload = event.payload

        if event_type in {EventType.SPEECH_STARTED, EventType.USER_SPEECH}:
            if event_type == EventType.USER_SPEECH and payload.get("status") != "started":
                if payload.get("status") == "ended":
                    await self.update_state(listening=False)
                    return True
                return False
            await self.update_state(
                active_turn_id=None,
                active_speaker="user",
                turn_state=TurnState.LISTENING,
                assistant_busy=False,
                speaking=False,
                listening=True,
            )
            return True

        if event_type == EventType.SPEECH_ENDED:
            await self.update_state(listening=False)
            return True

        if event_type == EventType.CONVERSATION_TURN_STARTED:
            turn_id = payload.get("turn_id")
            if not isinstance(turn_id, str):
                return False
            speaker = payload.get("speaker", "user")
            if speaker == "assistant":
                return await self._begin_assistant_response(turn_id)
            await self.update_state(
                active_turn_id=turn_id,
                active_speaker=speaker,
                turn_state=TurnState.THINKING,
                assistant_busy=True,
                speaking=False,
                listening=False,
            )
            return True

        if event_type in {EventType.ASSISTANT_RESPONSE, EventType.ASSISTANT_RESPONSE_STARTED}:
            status = payload.get("status") if event_type == EventType.ASSISTANT_RESPONSE else "started"
            turn_id = payload.get("turn_id")
            if not isinstance(turn_id, str):
                return False
            if status == "started":
                return await self._begin_assistant_response(turn_id)
            if status in {"completed", "cancelled"}:
                return await self._finish_assistant_response(turn_id, status)
            return False

        if event_type in {
            EventType.ASSISTANT_RESPONSE_COMPLETED,
            EventType.ASSISTANT_RESPONSE_CANCELLED,
        }:
            turn_id = payload.get("turn_id")
            if not isinstance(turn_id, str):
                return False
            return await self._finish_assistant_response(turn_id, event_type.value)

        return False

    async def _begin_assistant_response(self, turn_id: str) -> bool:
        async with self._lock:
            if self._state.listening or (
                self._state.active_speaker == "user"
                and self._state.turn_state != TurnState.THINKING
            ):
                return False
            if (
                self._state.active_turn_id not in {None, turn_id}
                and self._state.turn_state in {TurnState.THINKING, TurnState.RESPONDING}
            ):
                return False
            if (
                self._state.active_turn_id == turn_id
                and self._state.turn_state == TurnState.RESPONDING
            ):
                return False
            self._state.active_turn_id = turn_id
            self._state.active_speaker = "assistant"
            self._state.turn_state = TurnState.RESPONDING
            self._state.assistant_busy = True
            self._state.speaking = True
            self._state.listening = False
            self._state.last_activity_ts = time.time()
            state = CognitiveState(**self._state.__dict__)

        await self._publish_state_update(
            "assistant_response_started", state, turn_id=turn_id
        )
        return True

    async def _finish_assistant_response(self, turn_id: str, reason: str) -> bool:
        async with self._lock:
            # A speech interruption clears the active turn.  Late completion
            # or cancellation from that turn must not resurrect or clear the
            # replacement user state.
            if self._state.active_turn_id != turn_id:
                return False
            self._state.active_turn_id = None
            self._state.active_speaker = None
            self._state.turn_state = TurnState.IDLE
            self._state.assistant_busy = False
            self._state.speaking = False
            self._state.listening = False
            self._state.last_activity_ts = time.time()
            state = CognitiveState(**self._state.__dict__)

        await self._publish_state_update(
            "assistant_response_cancelled" if reason.endswith("CANCELLED") or reason == "cancelled"
            else "assistant_response_completed",
            state,
            turn_id=turn_id,
        )
        return True

    async def _publish_state_update(
        self,
        reason: str,
        state: CognitiveState,
        **extra: Any,
    ) -> None:
        if self.event_bus is None or not getattr(self.event_bus, "_running", True):
            return
        await self.event_bus.publish(
            Event.create(
                EventType.STATE_UPDATED,
                {"reason": reason, **extra, **state.__dict__},
                "cognitive_engine",
            )
        )

    async def reset_interruption(self):
        async with self._lock:
            self._state.interruption_owner = None

    async def update_tone(self, utterance: str, history: Optional[list[str]] = None):
        """Update emotional tone based on user input."""
        from core.cognition.tone_detector import detect_tone

        new_tone = detect_tone(utterance, history)
        if new_tone != self.current_tone:
            logger.debug(f"tone_shift: {self.current_tone} → {new_tone}")
            self.current_tone = new_tone

    def get_tone_context(self) -> str:
        """Return tone-modulated system context string."""
        tone_adjectives = {
            "confident": "You are direct, assured, and confident. You speak without hedging.",
            "cautious": "You are measured, qualified, and thoughtful. Use conditional language.",
            "curious": "You are inquisitive, exploratory, and open-minded. Dig deeper into topics.",
            "warm": "You are supportive, friendly, and compassionate. Show empathy and care.",
            "neutral": "You are calm, clear, and neutral. Use straightforward wording.",
            "factual": "You are precise and evidence-focused. State only supported facts and uncertainty.",
        }
        return tone_adjectives.get(self.current_tone, tone_adjectives["curious"])
