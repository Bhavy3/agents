from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from core.events.bus import EventBus
from core.events.event_types import EventType
from core.events.models import Event
from core.logging.logger import get_logger


from core.metrics.metrics import RuntimeMetrics


@dataclass(slots=True)
class StreamState:
    stream_id: str
    chunks: list[str] = field(default_factory=list)
    start_time: float = field(default_factory=time.perf_counter)
    last_chunk_at: float = field(default_factory=time.perf_counter)
    is_complete: bool = False
    is_cancelled: bool = False
    is_timed_out: bool = False


class ResponseAggregator:
    """Aggregates stream chunks into a finalized deterministic response."""
    
    def __init__(self, event_bus: EventBus, metrics: RuntimeMetrics | None = None) -> None:
        self.event_bus = event_bus
        self.metrics = metrics
        self.active_streams: dict[str, StreamState] = {}
        self.logger = get_logger("llm.aggregator")

    async def start_stream(self, model: str, correlation_id: str | None = None) -> str:
        stream_id = str(uuid.uuid4())[:8]
        self.active_streams[stream_id] = StreamState(stream_id=stream_id)
        if self.metrics:
            self.metrics.stream_count += 1
        
        await self.event_bus.publish(
            Event.create(
                EventType.STREAM_STARTED,
                {"stream_id": stream_id, "model": model},
                "aggregator",
                correlation_id,
            )
        )
        return stream_id

    async def add_chunk(self, stream_id: str, chunk: str, correlation_id: str | None = None) -> None:
        state = self.active_streams.get(stream_id)
        if not state or state.is_complete or state.is_cancelled:
            return

        state.chunks.append(chunk)
        state.last_chunk_at = time.perf_counter()
        if self.metrics:
            self.metrics.chunk_count += 1
        
        await self.event_bus.publish(
            Event.create(
                EventType.STREAM_CHUNK,
                {"stream_id": stream_id, "chunk": chunk, "index": len(state.chunks) - 1},
                "aggregator",
                correlation_id,
            )
        )

    async def complete_stream(self, stream_id: str, correlation_id: str | None = None) -> str:
        state = self.active_streams.pop(stream_id, None)
        if not state:
            return ""

        state.is_complete = True
        full_text = "".join(state.chunks)
        duration = time.perf_counter() - state.start_time
        
        await self.event_bus.publish(
            Event.create(
                EventType.STREAM_COMPLETED,
                {
                    "stream_id": stream_id,
                    "full_text": full_text,
                    "chunk_count": len(state.chunks),
                    "duration": round(duration, 3),
                    "cancelled": False,
                    "timed_out": False,
                    "degraded_mode": False,
                },
                "aggregator",
                correlation_id,
            )
        )
        return full_text

    async def cancel_stream(self, stream_id: str, reason: str, correlation_id: str | None = None) -> None:
        state = self.active_streams.pop(stream_id, None)
        if not state:
            return

        state.is_cancelled = True
        if self.metrics:
            self.metrics.stream_error_count += 1
        await self.event_bus.publish(
            Event.create(
                EventType.STREAM_CANCELLED,
                {"stream_id": stream_id, "reason": reason},
                "aggregator",
                correlation_id,
            )
        )

    async def handle_timeout(self, stream_id: str, timeout_type: str, correlation_id: str | None = None) -> None:
        state = self.active_streams.pop(stream_id, None)
        if not state:
            return

        state.is_timed_out = True
        if self.metrics:
            self.metrics.stream_error_count += 1
        await self.event_bus.publish(
            Event.create(
                EventType.STREAM_TIMEOUT,
                {"stream_id": stream_id, "timeout_type": timeout_type},
                "aggregator",
                correlation_id,
            )
        )
