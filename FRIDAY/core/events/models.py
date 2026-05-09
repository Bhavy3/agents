from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import IntEnum, StrEnum
from typing import Any
from uuid import uuid4

from core.events.event_types import EventType


class EventPriority(IntEnum):
    CRITICAL = 0
    HIGH = 1
    NORMAL = 5
    LOW = 9


class EventState(StrEnum):
    CREATED = "created"
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    DROPPED = "dropped"


@dataclass(slots=True)
class Event:
    event_type: EventType
    event_id: str = field(default_factory=lambda: str(uuid4()))
    payload: dict[str, Any] = field(default_factory=dict)
    source: str = "system"
    priority: EventPriority = EventPriority.NORMAL
    correlation_id: str = field(default_factory=lambda: str(uuid4()))
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    state: EventState = EventState.CREATED
    version: str = "1.0"

    @classmethod
    def create(
        cls,
        event_type: EventType,
        payload: dict[str, Any] | None = None,
        source: str = "system",
        correlation_id: str | None = None,
        priority: EventPriority = EventPriority.NORMAL,
        version: str = "1.0",
    ) -> Event:
        return cls(
            event_type=event_type,
            event_id=str(uuid4()),
            payload=payload or {},
            source=source,
            priority=priority,
            correlation_id=correlation_id or str(uuid4()),
            state=EventState.CREATED,
            version=version,
        )

    def transition(self, new_state: EventState) -> None:
        self.state = new_state
