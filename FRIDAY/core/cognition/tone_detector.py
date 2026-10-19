"""Tone detection module for emotional presence."""
from typing import Optional


def detect_tone(utterance: str, history: Optional[list[str]] = None, default: str = "curious") -> str:
    """Infer emotional tone from utterance and conversation history."""
    # Keep tone inference explicit and delivery-focused. Polite requests remain
    # supported for compatibility; explicit self-reports provide stronger cues.

    utterance_lower = utterance.lower()

    confidence_keywords = {
        "can you", "help", "do this", "execute", "build", "fix",
        "certain", "confident", "definitely", "absolutely", "no doubt",
    }
    caution_keywords = {
        "not sure", "maybe", "unsure", "could you", "would you", "might",
        "may be mistaken", "may be wrong", "please check carefully",
    }
    curiosity_keywords = {
        "explore", "dig", "understand why", "how come", "deep dive",
        "wonder", "curious", "why does", "how does",
    }
    warmth_keywords = {
        "frustrated", "worried", "upset", "thanks", "appreciate", "sorry",
        "discouraged", "overwhelmed", "encouragement", "need support",
        "could use support",
    }
    factual_keywords = {
        "exact date", "numeric measurement", "numeric measurements", "facts only",
        "data only", "numbers only", "evidence only",
    }
    neutral_keywords = {
        "please explain", "explain how", "please describe", "neutral tone",
        "straightforward explanation",
    }

    confidence_score = sum(1 for kw in confidence_keywords if kw in utterance_lower)
    caution_score = sum(1 for kw in caution_keywords if kw in utterance_lower)
    curiosity_score = sum(1 for kw in curiosity_keywords if kw in utterance_lower)
    warmth_score = sum(1 for kw in warmth_keywords if kw in utterance_lower)
    factual_score = sum(1 for kw in factual_keywords if kw in utterance_lower)
    neutral_score = sum(1 for kw in neutral_keywords if kw in utterance_lower)

    scores = {
        "warm": warmth_score,
        "cautious": caution_score,
        "curious": curiosity_score,
        "confident": confidence_score,
        "factual": factual_score,
        "neutral": neutral_score,
    }

    # Fallback to default if no strong signal
    max_score = max(scores.values())
    if max_score == 0:
        return default  # default neutral tone

    return max(scores, key=scores.get)
