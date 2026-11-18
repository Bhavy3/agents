"""Capability grounding: refuse requests that no capability can actually serve.

A request for private data -- an inbox, a calendar, messages -- must never be
answered from the chat model's imagination. Coverage is read from the
machine-readable ``covers`` field on capability manifests, never inferred from
prose: a description that merely mentions "email" does not grant access to an
inbox.

The detection vocabulary is deliberately narrow. It only fires when the user is
asking about their own data, so "what is email" or "explain how email works"
stay ordinary conversation.
"""

from __future__ import annotations

import re
from typing import Mapping

from ..logging.logger import get_logger
from .capability import Capability
from .capability_loader import CapabilityLoader

logger = get_logger("tools.grounding")

# Private data domains and the words that indicate a request for the user's own.
PRIVATE_DOMAINS: dict[str, str] = {
    "email": r"(?:e-?mail|inbox|gmail|mailbox)",
    "calendar": r"(?:calendar|meetings?|appointments?)",
    "messages": (
        r"(?:whatsapp|telegram|slack|discord|teams|messenger|imessage|"
        r"sms|text\s+messages|dms?|chat\s+messages)"
    ),
    "clipboard": r"(?:clipboard|copy\s+buffer)",
}

# An action cue or a possessive is required, which keeps conceptual questions out.
_ACTION_CUE = (
    # `summar\w*` is deliberate: `summar` + \b never matched "summarize",
    # which let "summarize my slack messages" through the gate.
    r"(?:find|check|read|search|summar\w*|show|list|open|send|reply|"
    r"look\s+(?:at|in|for)|any|something|new|latest|unread)"
)

_PATTERNS: dict[str, re.Pattern[str]] = {
    domain: re.compile(
        rf"\b{_ACTION_CUE}\b.{{0,40}}\b{term}\b|\bmy\s+{term}\b",
        re.IGNORECASE,
    )
    for domain, term in PRIVATE_DOMAINS.items()
}

_LABEL = {
    "email": "read your email",
    "calendar": "read your calendar",
    "messages": "read your messages",
    "clipboard": "read your clipboard",
}

# A destructive verb aimed at a location outside the workspace is refused
# before planning: it cannot be undone and no capability may do it.
_DESTRUCTIVE_VERB = re.compile(
    r"\b(?:delete|remove|erase|wipe|format|destroy|drop|rename|overwrite|chmod)\b",
    re.IGNORECASE,
)
_OUTSIDE_WORKSPACE = re.compile(
    r"\b(?:desktop|documents|downloads|pictures|videos|music|onedrive|"
    r"one\s+drive|system32|program\s+files|every\s+file|all\s+files|"
    r"whole\s+drive|my\s+files)\b|[a-z]:\\",
    re.IGNORECASE,
)


def destructive_request(text: str) -> str | None:
    """Describe the destructive outside-workspace action, or None."""
    if not text:
        return None
    if _DESTRUCTIVE_VERB.search(text) and _OUTSIDE_WORKSPACE.search(text):
        return "change or delete files outside my workspace"
    return None


def destructive_refusal(reason: str) -> str:
    return (
        f"I won't {reason}. It cannot be undone and it is outside the folder I am "
        "allowed to touch, so I am not doing it. If you want it, run it yourself "
        "or move those files into my workspace first."
    )

_snapshot: dict[str, Capability] | None = None


def capabilities_snapshot() -> dict[str, Capability]:
    """Load manifest coverage once per process; degrade to empty, never raise."""
    global _snapshot
    if _snapshot is None:
        try:
            _snapshot = CapabilityLoader().load_all()
        except Exception:
            logger.exception("capability_snapshot_failed")
            _snapshot = {}
    return _snapshot


def refresh_capabilities() -> dict[str, Capability]:
    """Re-read manifests, for after a capability is acquired at runtime."""
    global _snapshot
    _snapshot = None
    return capabilities_snapshot()


def covered_domains(capabilities: Mapping[str, Capability]) -> set[str]:
    return {
        token
        for capability in capabilities.values()
        for token in getattr(capability, "covers", ())
    }


def requested_domains(text: str) -> list[str]:
    """Private domains the request is asking about, in a stable order."""
    return [domain for domain, pattern in _PATTERNS.items() if pattern.search(text or "")]


def uncovered_domain(text: str, capabilities: Mapping[str, Capability] | None = None) -> str | None:
    """First requested private domain that no capability declares it can serve."""
    capabilities = capabilities_snapshot() if capabilities is None else capabilities
    covered = covered_domains(capabilities)
    for domain in requested_domains(text):
        if domain not in covered:
            return domain
    return None


def grounding_refusal(domain: str) -> str:
    label = _LABEL.get(domain, f"access your {domain}")
    return (
        f"I don't have a capability to {label} yet, so I'm not going to guess at it. "
        "That needs a connected account with your permission before I can answer."
    )
