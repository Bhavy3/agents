"""Latency predictor and budget inference for adaptive intelligence routing."""

def estimate_latency(utterance: str, model: str) -> float:
    """Estimate response time in seconds based on utterance and model."""
    # ponytail: linear token heuristic, calibrate coefficients if hardware changes
    tokens_estimate = len(utterance.split()) * 1.3

    if model == "3b":
        # 3B: fast, ~1-2s for typical query
        return 0.88 + (tokens_estimate * 0.05)
    elif model == "7b":
        # 7B: thorough, ~9-18s depending on complexity
        return 2.0 + (tokens_estimate * 0.8)
    else:
        return 10.0  # unknown


def infer_latency_budget(utterance: str) -> float:
    """Detect user's urgency and infer acceptable wait time."""
    # Budget keywords: "quick" / "asap" / "now" = 2s, "analyze" / "deeply" = 20s
    urgency_keywords = {
        "quick": 2.0, "asap": 2.0, "now": 2.0, "fast": 2.5,
        "immediate": 1.5, "right now": 1.5,
    }
    patience_keywords = {
        "analyze": 20.0, "deeply": 20.0, "thoroughly": 20.0,
        "detail": 15.0, "comprehensive": 18.0,
    }

    utterance_lower = utterance.lower()

    for kw, budget in urgency_keywords.items():
        if kw in utterance_lower:
            return budget

    for kw, budget in patience_keywords.items():
        if kw in utterance_lower:
            return budget

    return 5.0  # default: user will wait ~5 seconds
