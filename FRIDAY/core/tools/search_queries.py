"""Bounded, site-independent query preparation; keep the original task separate."""
import re

MAX_QUESTION_CHARS = 2500


def compact_question(text: str) -> str:
    """Remove repeated clauses, never silently discard the question's ending."""
    normalized = " ".join(text.split())
    parts = re.split(r"(?<=[.!?।])\s+", normalized)
    return " ".join(dict.fromkeys(parts))


def search_queries(question: str) -> list[str]:
    text = compact_question(question)
    text = re.sub(r"\bConsider\s+[^.!?]+[.!?]", "", text, flags=re.I)
    text = re.sub(r"\bCRITICAL FINAL CONSTRAINT:\s*", "", text, flags=re.I)
    # Answer-format instructions are not useful search keywords. Constraints
    # remain in the original question supplied to answer synthesis.
    text = re.sub(r"\b(?:give|provide|cite) (?:the |me |an? )?(?:exact product URL|sources?|source links|verified current prices).*", "", text, flags=re.I)
    text = re.sub(r"\b(?:if (?:it|none|you)|do not (?:invent|substitute)|correct the premise|distinguish measured|recommend one using).*", "", text, flags=re.I)
    text = re.sub(r"\b(?:search(?: the)?(?: web)?(?: for)?|official sources:)\s*", "", text, flags=re.I)
    text = re.sub(r"\b(?:and )?(?:say if|explain if).*", "", text, flags=re.I)
    domains = re.findall(
        r"(?<![\w.-])([\w-]+\.(?:org|com|gov|edu|net)(?:\.[a-z]{2})?)(?![\w.-])",
        text,
        flags=re.I,
    )
    text = re.sub(r"\bUse\s+\S+\s+and exclude.*", "", text, flags=re.I)
    text = re.sub(r"\bNOT\s+([^.;]+)", lambda m: '-"' + m[1].strip() + '"', text)
    text = " ".join(text.split()).strip(" .:;")
    sites = " ".join(f"site:{domain.lower()}" for domain in domains)
    primary = f"{text} {sites}".strip()
    # Token deduplication retains numbers, negation, and late constraints.
    tokens = list(dict.fromkeys(primary.split()))
    if len(primary) > 500:
        primary = " ".join(tokens)
    if len(primary) > 500:
        # A query is a retrieval probe, not the task specification. Sample both
        # ends; the complete deduplicated task is retained for synthesis.
        primary = primary[:240].rsplit(" ", 1)[0] + " " + primary[-240:].split(" ", 1)[-1]
    stop = {"the", "a", "an", "of", "for", "in", "and", "or", "is", "are", "was", "when", "did", "what", "which",
            "compare", "popular", "please", "tell", "me", "using", "from", "current", "as", "with", "consider"}
    keywords = " ".join(word for word in tokens if word.lower() not in stop)
    if len(keywords) > 500:
        keywords = primary
    return list(dict.fromkeys(q for q in (primary, keywords) if q))


def relevance(record: dict, query: str) -> float:
    words = set(re.findall(r"[\w-]{3,}", query.lower()))
    text = str(record.get("title", "")) + " " + str(record.get("body", ""))
    lower = text.lower()
    matched = sum(word in lower for word in words)
    return matched / max(1, len(words))
