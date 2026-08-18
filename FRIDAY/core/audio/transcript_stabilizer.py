import logging
import re
from typing import Any
from dataclasses import dataclass, field
from core.events.bus import EventBus
from core.events.event_types import EventType
from core.events.models import Event

@dataclass
class StabilizerConfig:
    min_stable_frames: int = 2
    meaningful_delta_length: int = 5
    max_history: int = 10

class TranscriptStabilizer:
    """
    Prevents unstable partial transcript spam from STT models.
    Only emits a partial transcript if the token survived N frames,
    or the delta is considered meaningful.
    """
    def __init__(self, event_bus: EventBus, config: StabilizerConfig | None = None, metrics: Any = None):
        self.event_bus = event_bus
        self.config = config or StabilizerConfig()
        self.metrics = metrics
        self.logger = logging.getLogger("audio.transcript_stabilizer")
        
        self._last_emitted_text = ""
        self._current_stable_text = ""
        self._frames_stable = 0

    async def process_partial(self, segment_id: str, new_text: str) -> None:
        new_text = new_text.strip()
        
        if not new_text:
            return

        if new_text == self._current_stable_text:
            self._frames_stable += 1
        else:
            # Check if this is a mutation (revision) or just an addition
            if self._last_emitted_text and not new_text.startswith(self._last_emitted_text[:len(self._last_emitted_text)//2]):
                self.logger.debug("transcript_revision_dropped", extra={"old": self._last_emitted_text, "new": new_text})
                if self.metrics:
                    self.metrics.partial_revisions_dropped += 1
            
            self._current_stable_text = new_text
            self._frames_stable = 0

        # Decide whether to emit. We keep partial transcript stabilization internal
        # and avoid introducing extra USER_SPEECH partial events into the pipeline.
        delta = len(new_text) - len(self._last_emitted_text)
        is_stable_enough = self._frames_stable >= self.config.min_stable_frames
        is_meaningful_delta = delta >= self.config.meaningful_delta_length
        
        if (is_stable_enough or is_meaningful_delta) and new_text != self._last_emitted_text:
            self.logger.debug(
                "transcript_stabilizer_partial_stable",
                extra={"segment_id": segment_id, "text": new_text, "is_stable": is_stable_enough},
            )
            self._last_emitted_text = new_text

    def reset(self) -> None:
        self._last_emitted_text = ""
        self._current_stable_text = ""
        self._frames_stable = 0

    def merge_final_piece(self, current_text: str, next_piece: str) -> str:
        """Merge final STT pieces without keeping prefix-refinement duplicates."""
        current_text = self.stabilize_final(current_text)
        next_piece = self.stabilize_final(next_piece)

        if not current_text:
            return next_piece
        if not next_piece:
            return current_text
        if current_text.endswith(next_piece):
            return current_text
        if next_piece.startswith(current_text):
            return next_piece

        words = current_text.split()
        if words:
            last_word = words[-1]
            if len(last_word) >= 2 and next_piece.lower().startswith(last_word.lower()):
                words[-1] = next_piece
                return " ".join(words)

        return f"{current_text} {next_piece}".strip()

    def stabilize_final(self, text: str) -> str:
        """Normalize final transcripts that contain immediate duplicate refinements."""
        text = " ".join(text.strip().split())
        if not text:
            return ""

        words = text.split()
        deduped: list[str] = []
        for word in words:
            if not deduped:
                deduped.append(word)
                continue
            previous = deduped[-1]
            previous_lower = previous.lower()
            word_lower = word.lower()
            if word_lower == previous_lower:
                continue
            if len(previous) >= 2 and word_lower.startswith(previous_lower):
                deduped[-1] = word
                continue
            deduped.append(word)
        text = " ".join(deduped)

        if " " not in text:
            collapsed = self._collapse_prefix_refinement(text)
            if collapsed != text:
                return collapsed

        return re.sub(r"\b(\w+)\s+\1\b", r"\1", text, flags=re.IGNORECASE)

    def _collapse_prefix_refinement(self, text: str) -> str:
        n = len(text)
        if n < 2:
            return text
        # e.g. "hhello" -> prefix "h", suffix "hello"
        for split_at in range(n - 1, 0, -1):
            prefix = text[:split_at]
            suffix = text[split_at:]
            if len(suffix) > len(prefix) and suffix.lower().startswith(prefix.lower()):
                return suffix
        return text
