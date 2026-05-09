from __future__ import annotations

import gc
import tracemalloc
from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class MemorySample:
    current_bytes: int
    peak_bytes: int
    queue_depth: int
    gc_objects: int


class MemoryMonitor:
    def __init__(self, growth_warning_bytes: int) -> None:
        self.growth_warning_bytes = growth_warning_bytes
        self._baseline: MemorySample | None = None
        self._last: MemorySample | None = None
        if not tracemalloc.is_tracing():
            tracemalloc.start()

    def sample(self, queue_depth: int) -> MemorySample:
        current, peak = tracemalloc.get_traced_memory()
        sample = MemorySample(
            current_bytes=current,
            peak_bytes=peak,
            queue_depth=queue_depth,
            gc_objects=len(gc.get_objects()),
        )
        if self._baseline is None:
            self._baseline = sample
        self._last = sample
        return sample

    def warning_reason(self, sample: MemorySample) -> str | None:
        if self._baseline is None:
            return None
        growth = sample.current_bytes - self._baseline.current_bytes
        if growth > self.growth_warning_bytes:
            return f"memory growth exceeded threshold: {growth} bytes"
        return None

    def trend(self) -> dict[str, int]:
        if self._baseline is None or self._last is None:
            return {"current_bytes": 0, "growth_bytes": 0, "peak_bytes": 0, "gc_objects": 0}
        return {
            "current_bytes": self._last.current_bytes,
            "growth_bytes": self._last.current_bytes - self._baseline.current_bytes,
            "peak_bytes": self._last.peak_bytes,
            "gc_objects": self._last.gc_objects,
        }
