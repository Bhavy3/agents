import logging
import re
from dataclasses import dataclass
from core.events.bus import EventBus
from core.events.event_types import EventType
from core.events.models import Event

@dataclass
class BufferConfig:
    min_chunk_length: int = 15
    sentence_delimiters: tuple[str, ...] = (".", "!", "?", "\n")
    pause_delimiters: tuple[str, ...] = (",", ";", ":", " - ")

class SemanticResponseBuffer:
    """
    Prevents LLM token jitter and ensures the TTS engine receives stable,
    meaningful chunks of text (e.g., complete sentences or clauses) instead
    of individual tokens.
    """
    def __init__(self, event_bus: EventBus, config: BufferConfig | None = None):
        self.event_bus = event_bus
        self.config = config or BufferConfig()
        self.logger = logging.getLogger("orchestrator.response_buffer")
        
        self._buffer = ""
        self._turn_id = ""

    def set_turn_id(self, turn_id: str) -> None:
        self._turn_id = turn_id

    async def ingest_token(self, token: str) -> None:
        if not token:
            return
            
        self._buffer += token
        
        # Check for semantic boundaries
        if len(self._buffer) >= self.config.min_chunk_length:
            buffer_stripped = self._buffer.rstrip()
            if any(buffer_stripped.endswith(d) for d in self.config.sentence_delimiters):
                await self._flush("sentence_boundary", is_final=False)
            elif any(self._buffer.endswith(d + " ") for d in self.config.pause_delimiters):
                # Only flush on pauses if it's followed by a space to avoid mid-number commas
                await self._flush("pause_boundary", is_final=False)

    async def flush_final(self) -> None:
        """Called when the LLM stream completes to flush remaining text."""
        if self._buffer.strip():
            await self._flush("stream_completed", is_final=True)
        self._turn_id = ""

    def clear(self) -> None:
        self._buffer = ""
        self._turn_id = ""

    async def _flush(self, reason: str, is_final: bool) -> None:
        text_to_flush = self._buffer.strip()
        self._buffer = ""
        
        if not text_to_flush:
            return

        await self.event_bus.publish(Event.create(
            EventType.ASSISTANT_RESPONSE,
            {"status": "partial", "text": text_to_flush, "turn_id": self._turn_id, "is_final": is_final, "reason": reason},
            "semantic_buffer"
        ))
