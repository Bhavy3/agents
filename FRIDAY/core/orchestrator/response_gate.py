import asyncio
import logging
from core.events.bus import EventBus
from core.events.event_types import EventType
from core.events.models import Event
from core.personality.presence_timing import PresenceTimingEngine

class ResponseReadinessGate:
    """
    Prevents premature assistant replies by ensuring confidence stability
    and checking conversational readiness scoring.
    """
    def __init__(self, event_bus: EventBus, timing_engine: PresenceTimingEngine):
        self.event_bus = event_bus
        self.timing_engine = timing_engine
        self.logger = logging.getLogger("orchestrator.response_gate")
        
        self._gate_tasks: dict[str, asyncio.Task] = {}
        self._ready_event = asyncio.Event()

    async def wait_for_readiness(self, turn_id: str, text_length: int = 0, urgency: float = 0.0, momentum: float = 0.0) -> bool:
        """
        Blocks until the assistant is 'ready' to respond based on timing rules.
        Returns True if ready, False if the wait was cancelled (e.g., user started speaking again).
        """
        self._ready_event.clear()
        
        task = asyncio.create_task(
            self.timing_engine.enforce_readiness_delay(
                turn_id,
                text_length,
                urgency=urgency,
                momentum=momentum,
            )
        )
        self._gate_tasks[turn_id] = task
        
        try:
            await task
            self._ready_event.set()
            return True
        except asyncio.CancelledError:
            self.logger.debug("readiness_wait_cancelled", extra={"turn_id": turn_id})
            return False
        finally:
            self._gate_tasks.pop(turn_id, None)

    def cancel_wait(self, turn_id: str) -> None:
        """Cancel an active wait if the user interrupts."""
        task = self._gate_tasks.get(turn_id)
        if task and not task.done():
            task.cancel()
