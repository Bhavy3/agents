from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from core.executor.dry_run_actions import ExecutorResult

CommandHandler = Callable[[dict[str, str]], Awaitable[ExecutorResult]]


@dataclass(slots=True)
class CommandRegistry:
    _handlers: dict[str, CommandHandler] = field(default_factory=dict)

    def register(self, command_name: str, handler: CommandHandler) -> None:
        if command_name in self._handlers:
            raise ValueError(f"Command already registered: {command_name}")
        self._handlers[command_name] = handler

    def get(self, command_name: str) -> CommandHandler | None:
        return self._handlers.get(command_name)

    def names(self) -> list[str]:
        return sorted(self._handlers)
