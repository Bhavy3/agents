import time
import logging

class RuntimeClock:
    """
    Provides synchronized monotonic timing for the cognitive runtime.
    """
    def __init__(self):
        self._start_time = time.monotonic()
        self.logger = logging.getLogger("cognition.clock")

    def now(self) -> float:
        """Returns monotonic time since system start."""
        return time.monotonic() - self._start_time

    def timestamp(self) -> float:
        """Returns standard unix timestamp."""
        return time.time()

    def get_latency(self, start_monotonic: float) -> float:
        return self.now() - start_monotonic
