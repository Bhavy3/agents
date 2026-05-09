from __future__ import annotations

from core.executor.command_registry import CommandRegistry
from core.executor.dry_run_actions import (
    ExecutorResult,
    chat_response,
    show_help,
)
from core.router.rules import IntentName


def register(registry: CommandRegistry) -> None:
    async def help_handler(_: dict[str, str]):
        return await show_help()

    async def exit_handler(_: dict[str, str]):
        return ExecutorResult(
            success=True,
            message="Shutting down FRIDAY gracefully.",
            metadata={"intended_action": "shutdown_runtime", "scope": "friday_runtime"},
        )

    async def chat_handler(parameters: dict[str, str]):
        return await chat_response(parameters.get("text", ""))

    registry.register(IntentName.HELP.value, help_handler)
    registry.register(IntentName.EXIT.value, exit_handler)
    registry.register(IntentName.CHAT.value, chat_handler)
