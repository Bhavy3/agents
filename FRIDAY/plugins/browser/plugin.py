from __future__ import annotations

from core.executor.command_registry import CommandRegistry
from core.executor.dry_run_actions import search_google
from core.router.rules import IntentName


def register(registry: CommandRegistry) -> None:
    async def handle(parameters: dict[str, str]):
        return await search_google(parameters.get("query", ""))

    registry.register(IntentName.SEARCH_GOOGLE.value, handle)
