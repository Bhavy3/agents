from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class IntentName(StrEnum):
    OPEN_CHROME = "open_chrome"
    OPEN_FOLDER = "open_folder"
    SEARCH_GOOGLE = "search_google"
    HELP = "help"
    EXIT = "exit"
    CHAT = "chat"
    UNKNOWN = "unknown"


@dataclass(slots=True, frozen=True)
class Intent:
    name: IntentName
    confidence: float
    parameters: dict[str, str]
    source: str = "rules"


def route_by_rules(text: str) -> Intent | None:
    normalized = " ".join(text.strip().lower().split())
    if not normalized:
        return None

    if normalized in {"exit", "quit", "shutdown friday", "stop friday"}:
        return Intent(IntentName.EXIT, 1.0, {})

    if normalized in {"help", "what can you do", "commands"}:
        return Intent(IntentName.HELP, 1.0, {})

    if normalized in {"open chrome", "start chrome", "launch chrome"}:
        return Intent(IntentName.OPEN_CHROME, 1.0, {})

    if normalized.startswith("open folder"):
        folder = text.strip()[len("open folder") :].strip() or "."
        return Intent(IntentName.OPEN_FOLDER, 0.95, {"path": folder})

    for prefix in ("search google for ", "google ", "search "):
        if normalized.startswith(prefix):
            query = text.strip()[len(prefix) :].strip()
            if query:
                return Intent(IntentName.SEARCH_GOOGLE, 0.95, {"query": query})

    return None
