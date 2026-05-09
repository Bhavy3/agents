from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


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
            "active_workers": self.active_workers,
            "queue_state": self.queue_state,
            "metrics": self.metrics,
            "task_counts": self.task_counts,
            "memory_usage": self.memory_usage,
            "event_rates": self.event_rates,
            "anomalies": self.anomalies,
        }
