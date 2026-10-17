from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


def _json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


@dataclass(slots=True, frozen=True)
class RuntimeSnapshot:
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    active_workers: list[dict[str, object]] = field(default_factory=list)
    queue_state: dict[str, int | float] = field(default_factory=dict)
    metrics: dict[str, float | int] = field(default_factory=dict)
    task_counts: dict[str, int] = field(default_factory=dict)
    memory_usage: dict[str, int] = field(default_factory=dict)
    event_rates: dict[str, float] = field(default_factory=dict)
    anomalies: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "created_at": self.created_at.isoformat(),
            "active_workers": _json_safe(self.active_workers),
            "queue_state": _json_safe(self.queue_state),
            "metrics": _json_safe(self.metrics),
            "task_counts": _json_safe(self.task_counts),
            "memory_usage": _json_safe(self.memory_usage),
            "event_rates": _json_safe(self.event_rates),
            "anomalies": _json_safe(self.anomalies),
        }
