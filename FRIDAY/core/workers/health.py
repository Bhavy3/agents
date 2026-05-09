from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from core.logging.logger import get_logger


class WorkerState(StrEnum):
    STARTING = "starting"
    RUNNING = "running"
    RESTARTING = "restarting"
    FAILED = "failed"
    DISABLED = "disabled"
    QUARANTINED = "quarantined"
    STOPPED = "stopped"


@dataclass(slots=True)
class WorkerHealth:
    name: str
    alive: bool = False
    state: WorkerState = WorkerState.STOPPED
    started_at: datetime | None = None
    last_heartbeat: datetime | None = None
    restart_count: int = 0
    current_task: str = "idle"

    def transition(self, state: WorkerState, task: str, alive: bool) -> None:
        previous_state = self.state
        self.state = state
        self.alive = alive
        self.current_task = task
        self.last_heartbeat = datetime.now(UTC)
        get_logger("workers.state").info(
            "worker_state_transition",
            extra={
                "worker": self.name,
                "from_state": previous_state.value,
                "to_state": state.value,
                "reason": task,
                "restart_count": self.restart_count,
            },
        )

    def mark_alive(self, task: str) -> None:
        self.alive = True
        self.transition(WorkerState.RUNNING, task, True)
        if self.started_at is None:
            self.started_at = datetime.now(UTC)

    def mark_starting(self) -> None:
        self.transition(WorkerState.STARTING, "starting", True)
        self.started_at = datetime.now(UTC)
        self.last_heartbeat = self.started_at

    def mark_failed(self) -> None:
        self.transition(WorkerState.FAILED, "failed", False)

    def mark_stopped(self) -> None:
        self.transition(WorkerState.STOPPED, "stopped", False)

    def mark_restarting(self) -> None:
        self.restart_count += 1
        self.transition(WorkerState.RESTARTING, "restarting", False)

    def mark_disabled(self) -> None:
        self.transition(WorkerState.DISABLED, "disabled", False)

    def mark_quarantined(self) -> None:
        self.transition(WorkerState.QUARANTINED, "quarantined", False)

    @property
    def uptime_seconds(self) -> float:
        if self.started_at is None:
            return 0.0
        return (datetime.now(UTC) - self.started_at).total_seconds()
