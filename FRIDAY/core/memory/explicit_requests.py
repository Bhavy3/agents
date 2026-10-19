"""Shared recognition for explicit memory writes and personal recall questions."""

import re


EXPLICIT_MEMORY_REQUEST = re.compile(
    r"^\s*(?:remember\s+(?:that|this|my|our)\s+|remember\s*:\s*|don't\s+forget\s+(?:that\s+)?|do\s+not\s+forget\s+(?:that\s+)?|save\s+this\s*:\s*)(.+?)\s*$",
    re.IGNORECASE,
)
PERSONAL_MEMORY_QUERY = re.compile(
    r"\b(?:my|mine|do you remember|what do you remember|"
    r"what (?:did|have) i (?:tell|told|say|said) you|"
    r"remember what i (?:told|said)|"
    r"what (?:was|is) (?:the )?(?:[\w'-]+\s+){0,4}"
    r"(?:code|color|name|date|number|address|favorite|preference|detail|fact|answer|password))\b",
    re.IGNORECASE,
)


def extract_explicit_memory_content(text: str) -> str | None:
    """Return the content only when the user used an explicit save phrase."""
    match = EXPLICIT_MEMORY_REQUEST.match(text or "")
    return match.group(1).strip() if match else None


def is_personal_memory_query(text: str) -> bool:
    """Identify queries that request a remembered personal fact."""
    return bool(PERSONAL_MEMORY_QUERY.search(text or ""))
