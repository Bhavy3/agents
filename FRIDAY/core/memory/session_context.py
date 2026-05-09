from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class SessionContext:
    last_intent: str | None = None
    last_target: str | None = None
    flags: dict[str, str] = field(default_factory=dict)
