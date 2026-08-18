"""Per-segment transcript state: Whisper partials are revisions, not additive chunks."""

from __future__ import annotations

from dataclasses import dataclass, field
import time

from core.audio.transcript_stabilizer import TranscriptStabilizer


def _stabilize(text: str) -> str:
    return TranscriptStabilizer(event_bus=None).stabilize_final(text)  # type: ignore[arg-type]


@dataclass
class TranscriptSession:
    segment_id: str
    latest_hypothesis: str = ""
    stabilized_text: str = ""
    final_text: str = ""
    started_at: float = field(default_factory=time.perf_counter)

    def revise(self, text: str) -> str:
        """Replace the evolving hypothesis instead of concatenating partials."""
        text = " ".join(text.strip().split())
        if not text:
            return self.latest_hypothesis

        previous = self.latest_hypothesis
        if not previous:
            self.latest_hypothesis = _stabilize(text)
            return self.latest_hypothesis

        prev_lower = previous.lower()
        new_lower = text.lower()
        stabilized = _stabilize(text)
        if len(stabilized) < len(text):
            self.latest_hypothesis = stabilized
        elif new_lower.startswith(prev_lower) and len(text) - len(previous) <= 3:
            self.latest_hypothesis = text
        elif prev_lower.startswith(new_lower):
            return previous
        else:
            self.latest_hypothesis = f"{previous} {text}".strip()
        return self.latest_hypothesis

    def set_final(self, text: str) -> str:
        self.final_text = _stabilize(text)
        self.latest_hypothesis = self.final_text
        return self.final_text
