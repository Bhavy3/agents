from __future__ import annotations

from core.executor.command_registry import CommandRegistry
from core.executor.dry_run_actions import open_folder
from core.router.rules import IntentName


def register(registry: CommandRegistry) -> None:
    async def handle(parameters: dict[str, str]):
        return await open_folder(parameters.get("path", "."))

    registry.register(IntentName.OPEN_FOLDER.value, handle)
