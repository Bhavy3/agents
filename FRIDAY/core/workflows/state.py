from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Optional


class WorkflowStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_CONFIRMATION = "waiting_confirmation"
    RECOVERING = "recovering"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(slots=True)
class WorkflowStep:
    id: str
    intent: str
    parameters: dict[str, Any]
    status: WorkflowStatus = WorkflowStatus.PENDING
    result: Optional[str] = None
    error: Optional[str] = None
    retry_count: int = 0
    depends_on: list[str] = field(default_factory=list)


@dataclass(slots=True)
class WorkflowGoal:
    id: str
    goal: str
    steps: list[WorkflowStep]
    status: WorkflowStatus = WorkflowStatus.PENDING
    created_at: float = field(default_factory=lambda: 0.0) # Will be set by engine
    metadata: dict[str, Any] = field(default_factory=dict)
