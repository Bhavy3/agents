import asyncio
import logging
from dataclasses import dataclass
from core.events.bus import EventBus
from core.events.event_types import EventType
from core.events.models import Event

@dataclass
class TimingProfile:
    base_delay_ms: float
    variance_ms: float
    soft_interrupt_fade_ms: float
    max_delay_ms: float = 650.0

class PresenceTimingEngine:
    """
    Central authority for conversational pacing.
    Controls reply delay, interruption softness, pause duration, and emotional pacing.
    """
    def __init__(self, event_bus: EventBus, metrics=None):
        self.event_bus = event_bus
        self.metrics = metrics
        self.logger = logging.getLogger("personality.presence_timing")
        
        # Default profile (neutral)
        self.current_profile = TimingProfile(
            base_delay_ms=300.0,
            variance_ms=150.0,
            soft_interrupt_fade_ms=250.0,
            max_delay_ms=650.0,
        )

    async def get_response_delay(self, text_length: int = 0, urgency: float = 0.0, momentum: float = 0.0) -> float:
        """Calculate dynamic delay based on current profile and input length."""
        import random
        delay = self.current_profile.base_delay_ms + random.uniform(0, self.current_profile.variance_ms)
        
        if text_length > 100:
            delay += 200.0

        if momentum > 0:
            delay -= min(160.0, momentum * 160.0)

        if urgency > 0:
            delay -= min(220.0, urgency * 220.0)

        delay = max(40.0, min(delay, self.current_profile.max_delay_ms))
        if self.metrics:
            self.metrics.avg_response_start_delay = delay / 1000.0
            self.metrics.response_timing_variance = self.current_profile.variance_ms / 1000.0

        return delay / 1000.0 # Return seconds

    def update_profile(self, profile_name: str) -> None:
        if profile_name == "frustrated":
            self.current_profile = TimingProfile(base_delay_ms=50.0, variance_ms=50.0, soft_interrupt_fade_ms=50.0, max_delay_ms=160.0)
        elif profile_name == "confused":
            self.current_profile = TimingProfile(base_delay_ms=500.0, variance_ms=300.0, soft_interrupt_fade_ms=300.0, max_delay_ms=900.0)
        elif profile_name == "casual":
            self.current_profile = TimingProfile(base_delay_ms=300.0, variance_ms=200.0, soft_interrupt_fade_ms=200.0, max_delay_ms=700.0)
        else:
            self.current_profile = TimingProfile(base_delay_ms=100.0, variance_ms=100.0, soft_interrupt_fade_ms=150.0, max_delay_ms=450.0)
        if self.metrics:
            self.metrics.cadence_shift_count += 1
            
        self.logger.debug("presence_timing_profile_updated", extra={"profile": profile_name})

    async def enforce_readiness_delay(self, turn_id: str, text_length: int = 0, urgency: float = 0.0, momentum: float = 0.0) -> None:
        """Wait naturally before allowing a response to start."""
        delay_seconds = await self.get_response_delay(text_length, urgency=urgency, momentum=momentum)
        await asyncio.sleep(delay_seconds)
