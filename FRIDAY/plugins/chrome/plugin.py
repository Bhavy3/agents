from __future__ import annotations

from core.executor.command_registry import CommandRegistry
from core.executor.dry_run_actions import open_chrome
from core.router.rules import IntentName


def register(registry: CommandRegistry) -> None:
    async def handle(_: dict[str, str]):
        return await open_chrome()

    registry.register(IntentName.OPEN_CHROME.value, handle)
