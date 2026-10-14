"""Query complexity detector for dynamic model escalation."""

def detect_query_complexity(utterance: str) -> str:
    """Returns 'simple', 'medium', or 'complex'."""
    # ponytail: keyword heuristic, embed/classifier if false positives grow
    escalation_keywords = {
        "not enough", "make me", "create", "build", "design",
        "analyze", "analysis", "explain", "code", "research", "deep dive"
    }
    de_escalation_keywords = {
        "weather", "time", "joke", "hi", "hello", "yapping",
        "thanks", "cool", "nice", "quick"
    }

    utterance_lower = utterance.lower()

    if any(kw in utterance_lower for kw in escalation_keywords):
        return "complex"
    elif any(kw in utterance_lower for kw in de_escalation_keywords):
        return "simple"
    else:
        return "medium"
