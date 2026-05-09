from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class MemoryType(StrEnum):
    PREFERENCE = "preference"
    ALIAS = "alias"
    PINNED_NOTE = "pinned_note"
    APPROVED_FACT = "approved_fact"
    CONVERSATION_SUMMARY = "conversation_summary"


@dataclass(slots=True, frozen=True)
class MemoryRecord:
    id: str
    type: MemoryType
    content: str
    created_at: float
    updated_at: float
    source: str
    confidence: float
    explicit_user_approved: bool
    metadata: dict[str, Any] = field(default_factory=dict)
