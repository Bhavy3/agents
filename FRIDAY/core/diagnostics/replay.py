from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from core.events.event_types import EventType
from core.events.models import Event


CRITICAL_REPLAY_EVENTS = {
    EventType.ERROR_OCCURRED,
    EventType.WORKER_FAILED,
    EventType.WORKER_RESTARTED,
    EventType.CRITICAL_WORKER_FAILURE,
    EventType.DEADLOCK_WARNING,
    EventType.MEMORY_WARNING,
    EventType.MALFORMED_EVENT_DROPPED,
    EventType.TASK_AUDIT_WARNING,
    EventType.BACKPRESSURE_APPLIED,
}


@dataclass(slots=True)
class FailureReplayRecorder:
    max_events: int = 200
    _events: deque[Event] = field(default_factory=deque)

    async def record(self, event: Event) -> None:
        if event.event_type not in CRITICAL_REPLAY_EVENTS:
            return
        self._events.append(event)
        while len(self._events) > self.max_events:
            self._events.popleft()

    def recent(self) -> list[dict[str, object]]:
        return [
            {
                "event_id": event.event_id,
                "event_type": event.event_type.value,
                "source": event.source,
                "created_at": event.created_at.isoformat(),
                "payload": event.payload,
                "correlation_id": event.correlation_id,
            }
            for event in self._events
        ]
