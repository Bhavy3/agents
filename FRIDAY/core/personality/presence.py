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
        # Cap to avoid frustration
        final_delay = min(delay, 3.0)
        
        await asyncio.sleep(final_delay)

    def get_acknowledgment(self, config: StyleConfig) -> str:
        """Returns a short acknowledgment string if appropriate for the tone."""
        import time
        now = time.time()
        
        if now - self._last_ack_time < self.ack_cooldown:
            return ""
            
        if config.pacing == "fast" or config.verbosity == "concise":
            return "" # No filler for fast modes
        
        acks = {
            "focused": ["Got it.", "Confirmed.", "Processing."],
            "patient": ["I see. Let's look into that.", "Understanding context...", "One moment, explaining now."],
            "friendly": ["Sure thing!", "Happy to help with that.", "Let's see what we can find."],
            "alert": ["Understood. Immediate action taken.", "On it."]
        }
        
        self._last_ack_time = time.time()
        return random.choice(acks.get(config.tone, ["Understood."]))
