from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field


@dataclass(slots=True)
class ShortTermMemory:
    max_items: int = 20
    _items: deque[str] = field(default_factory=deque)

    def add(self, item: str) -> None:
        self._items.append(item)
        while len(self._items) > self.max_items:
            self._items.popleft()

    def recent(self) -> list[str]:
        return list(self._items)
