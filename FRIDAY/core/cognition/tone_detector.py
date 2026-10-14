"""Tone detection module for emotional presence."""
from typing import Optional


def detect_tone(utterance: str, history: Optional[list[str]] = None, default: str = "curious") -> str:
    """Infer emotional tone from utterance and conversation history."""
    # Confidence markers: "can you", "help", "do this" (confident)
    # Uncertainty markers: "not sure", "maybe", "could you" (cautious)
    # Exploration markers: "explore", "dig into", "understand why" (curious)
    # Emotional markers: "frustrated", "worried", "upset", "thanks" (warm)

    utterance_lower = utterance.lower()
    history_lower = " ".join(history or []).lower()
    combined = utterance_lower + " " + history_lower

    confidence_keywords = {"can you", "help", "do this", "execute", "build", "fix"}
    caution_keywords = {"not sure", "maybe", "unsure", "could you", "would you", "might"}
    curiosity_keywords = {"explore", "dig", "understand why", "how come", "deep dive"}
    warmth_keywords = {"frustrated", "worried", "upset", "thanks", "appreciate", "sorry"}

    confidence_score = sum(1 for kw in confidence_keywords if kw in utterance_lower)
    caution_score = sum(1 for kw in caution_keywords if kw in utterance_lower)
    curiosity_score = sum(1 for kw in curiosity_keywords if kw in utterance_lower)
    warmth_score = sum(1 for kw in warmth_keywords if kw in combined)

    scores = {
        "warm": warmth_score,
        "cautious": caution_score,
        "curious": curiosity_score,
        "confident": confidence_score,
    }

    # Fallback to default if no strong signal
    max_score = max(scores.values())
    if max_score == 0:
        return default  # default neutral tone

    return max(scores, key=scores.get)
