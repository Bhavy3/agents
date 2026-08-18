from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class IntentName(StrEnum):
    OPEN_URL = "open_url"
    SEARCH_WEB = "search_web"
    LIST_DIR = "list_dir"
    READ_TEXT_FILE = "read_text_file"
    WRITE_TEXT_FILE = "write_text_file"
    SEARCH_FILES = "search_files"
    LAUNCH_APP = "launch_app"
    PRESS_KEY = "press_key"
    KEYBOARD_SHORTCUT = "keyboard_shortcut"
    MOVE_MOUSE_TO = "move_mouse_to"
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
        return Intent(IntentName.LAUNCH_APP, 1.0, {"app_name": "chrome"})

    if normalized.startswith("open folder"):
        folder = text.strip()[len("open folder") :].strip() or "."
        return Intent(IntentName.LIST_DIR, 0.95, {"path": folder})

    for prefix in ("search google for ", "google ", "search "):
        if normalized.startswith(prefix):
            query = text.strip()[len(prefix) :].strip()
            if query:
                return Intent(IntentName.SEARCH_WEB, 0.95, {"query": query})

    return None
