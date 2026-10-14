import asyncio
import random
from .models import StyleConfig


class PresenceManager:
    """Manages conversational timing, acknowledgment, and pacing."""

    def __init__(self):
        import time
        self._last_ack_time = 0.0
        self.ack_cooldown = 10.0 # Don't repeat acknowledgments within 10 seconds

    async def simulate_thinking_delay(self, config: StyleConfig, query_complexity: float = 0.5) -> None:
        """Simulates a natural delay before responding based on pacing and complexity."""
        base_delay = 0.2 # Minimum for realism
        
        if config.pacing == "fast":
            multiplier = 0.5
        elif config.pacing == "slow":
            multiplier = 2.0
        else:
            multiplier = 1.0

        # Randomized natural delay
        delay = (base_delay + (query_complexity * 1.5)) * multiplier
        # Keep the listening/thinking transition natural, but never let it
        # block routing for more than one second, regardless of complexity.
        final_delay = min(delay, 1.0)
        
        await asyncio.sleep(final_delay)

    def get_acknowledgment(self, config: StyleConfig, enable_presence_ack: bool = False) -> str:
        """Returns a short acknowledgment string if appropriate for the tone."""
        if not enable_presence_ack:
            return ""
            
        import time
        now = time.time()
        
        if now - self._last_ack_time < self.ack_cooldown:
            return ""
            
        self._last_ack_time = time.time()
        return "Hmm."