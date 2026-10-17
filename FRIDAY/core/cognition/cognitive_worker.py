import asyncio
import logging
from typing import Any
from core.events.bus import EventBus
from core.events.event_types import EventType
from core.events.models import Event
from core.workers.base_worker import BaseWorker
from core.cognition.cognitive_state import CognitiveStateEngine, TurnState
from core.cognition.attention_manager import AttentionManager, AttentionPriority
from core.cognition.priority_scheduler import PriorityScheduler
from core.cognition.runtime_clock import RuntimeClock

class CognitiveWorker(BaseWorker):
    """
    Main synchronization coordinator (Brain Stem).
    Coordinates VAD, STT, LLM, TTS, and Workflows into a single cognitive stream.
    """
    def __init__(
        self,
        event_bus: EventBus,
        state_engine: CognitiveStateEngine | None = None,
        *,
        cognitive_state: CognitiveStateEngine | None = None,
    ):
        super().__init__("cognition", event_bus)
        if state_engine is not None and cognitive_state is not None and state_engine is not cognitive_state:
            raise ValueError("state_engine and cognitive_state must reference the same engine")
        self.state_engine = state_engine or cognitive_state or CognitiveStateEngine(event_bus)
        self.attention = AttentionManager(event_bus)
        self.clock = RuntimeClock()
        
        self.logger = logging.getLogger("cognition.worker")

    async def run(self) -> None:
        # Canonical production lifecycle events.
        self.event_bus.subscribe(EventType.SPEECH_STARTED, self._handle_speech_started)
        self.event_bus.subscribe(EventType.SPEECH_ENDED, self._handle_speech_ended)
        self.event_bus.subscribe(EventType.CONVERSATION_TURN_STARTED, self._handle_turn_started)
        self.event_bus.subscribe(EventType.ASSISTANT_RESPONSE_STARTED, self._handle_assistant_response_started)
        self.event_bus.subscribe(EventType.ASSISTANT_RESPONSE_COMPLETED, self._handle_assistant_response_completed)
        self.event_bus.subscribe(EventType.ASSISTANT_RESPONSE_CANCELLED, self._handle_assistant_response_cancelled)

        # Legacy compatibility events retained for existing tests and callers.
        self.event_bus.subscribe(EventType.USER_SPEECH, self._handle_user_speech)
        self.event_bus.subscribe(EventType.ASSISTANT_RESPONSE, self._handle_assistant_response)
        self.event_bus.subscribe(EventType.ACTION_REQUEST, self._handle_action_started)
        self.event_bus.subscribe(EventType.STATE_UPDATED, self._handle_state_updated)
        
        await super().run()

    async def _handle_user_speech(self, event: Event):
        """Handle USER_SPEECH start/end/final."""
        status = event.payload.get("status")
        if status == "started":
            self.logger.info("speech_interruption_detected")
            await self.attention.acquire_attention("user_speech", AttentionPriority.CRITICAL_INTERRUPTION)
            await self.state_engine.apply_event(event)
        elif status == "ended":
            await self.state_engine.apply_event(event)
            await self.attention.release_attention("user_speech")

    async def _handle_speech_started(self, event: Event) -> None:
        """Handle the canonical live VAD event emitted by production audio."""
        self.logger.info("speech_interruption_detected")
        await self.attention.acquire_attention("user_speech", AttentionPriority.CRITICAL_INTERRUPTION)
        await self.state_engine.apply_event(event)

    async def _handle_speech_ended(self, event: Event) -> None:
        await self.state_engine.apply_event(event)
        await self.attention.release_attention("user_speech")

    async def _handle_turn_started(self, event: Event) -> None:
        await self.state_engine.apply_event(event)

    async def _handle_assistant_response_started(self, event: Event) -> None:
        await self.state_engine.apply_event(event)

    async def _handle_assistant_response_completed(self, event: Event) -> None:
        await self.state_engine.apply_event(event)

    async def _handle_assistant_response_cancelled(self, event: Event) -> None:
        await self.state_engine.apply_event(event)
    async def _handle_assistant_response(self, event: Event):
        """Assistant response start/completed."""
        await self.state_engine.apply_event(event)

    async def _handle_action_started(self, event: Event):
        """Action/Tool execution started."""
        await self.attention.acquire_attention("action", AttentionPriority.ACTIVE_TOOL)

    async def _handle_workflow_started(self, event: Event):
        """Workflow execution started."""
        await self.attention.acquire_attention("workflow", AttentionPriority.ACTIVE_WORKFLOW)

    async def _handle_state_updated(self, event: Event):
        reason = event.payload.get("reason", "")
        if reason.startswith("interruption_suppressed_"):
            # Revert cognitive speaker back to assistant/none on suppression
            state = await self.state_engine.get_state()
            if state.turn_state == TurnState.RESPONDING:
                await self.state_engine.update_state(active_speaker="assistant", listening=False, speaking=True)
            else:
                await self.state_engine.update_state(active_speaker=None, listening=False, speaking=False)

    async def work(self) -> None:
        while not self.should_stop:
            state = await self.state_engine.get_state()
            self.heartbeat(f"cognition [owner={self.attention.get_owner()} turn={state.turn_state} priority={int(self.attention.get_priority())}]")
            await asyncio.sleep(1.0)
