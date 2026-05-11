from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ToolRisk(StrEnum):
    SAFE = "SAFE"
    RESTRICTED = "RESTRICTED"
    DANGEROUS = "DANGEROUS"
    FORBIDDEN = "FORBIDDEN"


@dataclass(slots=True, frozen=True)
class ToolRequest:
    tool_name: str
    parameters: dict[str, Any]
    correlation_id: str
    risk_level: ToolRisk = ToolRisk.SAFE


@dataclass(slots=True, frozen=True)
class ToolResult:
    success: bool
    output: str
    error: str | None = None
    duration_ms: float = 0.0


@dataclass(slots=True)
class ActionNode:
    id: str
    tool_name: str
    parameters: dict[str, Any]
    depends_on: list[str] = field(default_factory=list)
    state: str = "PENDING"  # PENDING, RUNNING, COMPLETED, FAILED, CANCELLED


@dataclass(slots=True)
class ActionGraph:
    id: str
    nodes: list[ActionNode]
    max_depth: int = 10
    timeout_seconds: float = 30.0


@dataclass(slots=True, frozen=True)
class ToolAuditEntry:
    timestamp: float
    tool_name: str
    parameters: dict[str, Any]
    risk_level: ToolRisk
    success: bool
    duration_ms: float
    correlation_id: str
    error: str | None = None
