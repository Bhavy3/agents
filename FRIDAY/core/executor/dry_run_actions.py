from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass(slots=True, frozen=True)
class ExecutorResult:
    success: bool
    message: str
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    execution_time: float = 0.0
    requires_confirmation: bool = False


def _safe_result(message: str, intended_action: str, details: dict[str, Any] | None = None) -> ExecutorResult:
    return ExecutorResult(
        success=True,
        message=message,
        metadata={"intended_action": intended_action, **(details or {})},
        requires_confirmation=False,
    )


async def open_chrome() -> ExecutorResult:
    return _safe_result(
        "Dry-run: I would open Chrome.",
        "open_application:chrome",
        {"application": "chrome"},
    )


async def open_folder(path: str) -> ExecutorResult:
    return _safe_result(
        f"Dry-run: I would open folder: {path}",
        f"open_folder:{path}",
        {"path": path},
    )


async def search_google(query: str) -> ExecutorResult:
    return _safe_result(
        f"Dry-run: I would search Google for: {query}",
        f"search_google:{query}",
        {"query": query},
    )


async def show_help() -> ExecutorResult:
    commands = "open chrome, open folder <path>, search google for <query>, help, exit"
    return _safe_result(
        f"Available commands: {commands}",
        "show_help",
        {"commands": commands},
    )


async def chat_response(text: str) -> ExecutorResult:
    return _safe_result(
        f"I heard you. Phase 1 reasoning is intentionally limited. Very responsible of us, annoyingly.",
        f"chat_stub:{text}",
        {"text": text},
    )
