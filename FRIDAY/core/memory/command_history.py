from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass(slots=True, frozen=True)
class CommandHistoryEntry:
    command: str
    result: str
    success: bool
    intended_action: str
    metadata: dict[str, Any]
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(slots=True)
class CommandHistory:
    max_items: int = 100
    _items: list[CommandHistoryEntry] = field(default_factory=list)

    def add(self, entry: CommandHistoryEntry) -> None:
        self._items.append(entry)
        if len(self._items) > self.max_items:
            self._items = self._items[-self.max_items :]

    @property
    def last_command(self) -> CommandHistoryEntry | None:
        return self._items[-1] if self._items else None

    def recent(self) -> list[CommandHistoryEntry]:
        return list(self._items)
