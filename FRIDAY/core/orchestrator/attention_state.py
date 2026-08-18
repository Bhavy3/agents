import time
import logging
from dataclasses import dataclass, field
from core.events.bus import EventBus
from core.events.event_types import EventType
from core.events.models import Event

@dataclass
class AttentionState:
    active_subject: str = ""
    active_task: str = ""
    recent_entities: list[str] = field(default_factory=list)
    last_updated: float = 0.0
    momentum: float = 1.0 # 1.0 is full momentum, decays over time

class AttentionStateEngine:
    """
    Maintains the current conversational focus.
    Tracks active subject, recent entities, active task, and conversational momentum.
    """
    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus
        self.logger = logging.getLogger("orchestrator.attention_state")
        self.state = AttentionState()
        self.decay_rate_per_second = 0.05
        self.expiration_threshold_seconds = 120.0

    def update_attention(self, subject: str = "", task: str = "", entities: list[str] | None = None) -> None:
        """Update the active attention state based on new inputs."""
        now = time.perf_counter()
        
        # If the conversation has been idle too long, reset
        if now - self.state.last_updated > self.expiration_threshold_seconds and self.state.last_updated > 0:
            self._expire_attention("timeout")
            
        is_switch = False
        if subject and subject != self.state.active_subject:
            is_switch = True
            self.state.active_subject = subject
            
        if task and task != self.state.active_task:
            is_switch = True
            self.state.active_task = task
            
        if entities:
            # Keep the 5 most recent entities
            for e in entities:
                if e in self.state.recent_entities:
                    self.state.recent_entities.remove(e)
                self.state.recent_entities.append(e)
            self.state.recent_entities = self.state.recent_entities[-5:]
            
        self.state.last_updated = now
        
        if is_switch:
            # A switch in topic/task resets momentum but means we are starting a new thread
            self.state.momentum = 1.0
            
        # We don't want to make this an async function if it doesn't need to be,
        # but to publish events we'd need to. Let's just track state synchronously
        # and Orchestrator can publish the event.

    def get_current_momentum(self) -> float:
        if self.state.last_updated == 0:
            return 0.0
            
        elapsed = time.perf_counter() - self.state.last_updated
        momentum = max(0.0, self.state.momentum - (elapsed * self.decay_rate_per_second))
        return momentum
        
    def add_momentum(self, amount: float) -> None:
        self.state.momentum = min(1.0, self.get_current_momentum() + amount)
        self.state.last_updated = time.perf_counter()

    def _expire_attention(self, reason: str) -> None:
        self.logger.info("attention_expired", extra={"reason": reason})
        self.state = AttentionState()
