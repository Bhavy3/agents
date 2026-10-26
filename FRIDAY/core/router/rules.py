from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


FAST_CHAT_SOURCE = "fast_chat"

_FAST_CHAT_GREETING_RE = re.compile(
    r"^(?:hi|hello|hey|good morning|good afternoon|good evening)(?:\b|[,!.])",
    re.IGNORECASE,
)
_FAST_CHAT_GENERAL_QUESTION_RE = re.compile(
    r"^(?:what is|what are|why is|why are|why does|why do|how does|how do|"
    r"can you explain|explain|define|describe|give (?:me )?(?:an )?"
    r"(?:overview|explanation|introduction) of|what do you think)\b",
    re.IGNORECASE,
)
_FAST_CHAT_SMALL_TALK = {
    "how are you",
    "how are you today",
    "how are you doing",
    "how are you doing today",
    "what's up",
    "thanks",
    "thank you",
    "nice to meet you",
    "tell me a joke",
    "make me laugh",
}
_FAST_CHAT_ACTION_OR_DYNAMIC_RE = re.compile(
    r"\b(?:how\s+do\s+i|can\s+you\s+(?:help|show)\s+me|please|"
    r"search|look\s+up|latest|most\s+recent|recent|current|today|tonight|now|"
    r"live|real[- ]time|weather|capital|population|president|prime\s+minister|"
    r"release|version|price|score|winner|won|fifa|forecast|temperature|"
    r"stock|exchange\s+rate|address|location|"
    r"time|news|open|launch|start|run|execute|create|build|write|read|"
    r"delete|move|press|click|list|find\s+(?:a\s+)?file|directory|"
    r"folder|file|browser|chrome|status|restart|stop|shutdown|remember|"
    r"save|forget|workflow|project|code|shell|terminal|keyboard|mouse|"
    r"screen|send|email|set\s+up|turn\s+(?:on|off)|install|uninstall|"
    r"download|upload)\b",
    re.IGNORECASE,
)


class IntentName(StrEnum):
    OPEN_URL = "open_url"
    SEARCH_WEB = "search_web"
    RESEARCH_WEB = "research_web"
    OPEN_SECTION = "open_section"
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
    REMEMBER = "remember"
    GET_TIME = "get_time"
    CHAT = "chat"
    UNKNOWN = "unknown"


@dataclass(slots=True, frozen=True)
class Intent:
    name: IntentName
    confidence: float
    parameters: dict[str, str]
    source: str = "rules"


def fast_chat_intent(text: str) -> Intent | None:
    """Return a chat intent only for high-confidence, non-action utterances.

    This deliberately has a narrow allow-list.  Explicit tool phrases are
    handled by ``route_by_rules`` first, and anything that might be a tool,
    workflow, memory, or time-sensitive request is left for the LLM router.
    """
    normalized = " ".join(text.strip().lower().split())
    if not normalized or len(normalized) > 240:
        return None
    if normalized in _FAST_CHAT_SMALL_TALK:
        return Intent(IntentName.CHAT, 1.0, {}, source=FAST_CHAT_SOURCE)
    if _FAST_CHAT_ACTION_OR_DYNAMIC_RE.search(normalized):
        return None
    if _FAST_CHAT_GREETING_RE.match(normalized):
        return Intent(IntentName.CHAT, 1.0, {}, source=FAST_CHAT_SOURCE)
    if _FAST_CHAT_GENERAL_QUESTION_RE.match(normalized):
        return Intent(IntentName.CHAT, 1.0, {}, source=FAST_CHAT_SOURCE)
    return None


def route_by_rules(text: str) -> Intent | None:
    normalized = " ".join(text.strip().lower().split())
    if not normalized:
        return None

    if re.fullmatch(
        r"(?:what time is it(?: right now)?|what(?:'s| is) (?:the )?(?:local )?time(?: right now)?|"
        r"tell me (?:the )?(?:local )?time(?: right now)?|current time(?: please)?)\??",
        normalized,
    ):
        return Intent(IntentName.GET_TIME, 1.0, {})

    open_site = re.fullmatch(r"(?:open|launch)\s+([a-z0-9-]+(?:\.[a-z]{2,})?)", normalized)
    if open_site:
        site = open_site.group(1)
        url = f"https://www.{site}.com" if "." not in site else f"https://{site}"
        return Intent(IntentName.OPEN_URL, 1.0, {"url": url})

    if normalized in {"exit", "quit", "shutdown friday", "stop friday"}:
        return Intent(IntentName.EXIT, 1.0, {})

    if normalized in {"help", "what can you do", "commands"}:
        return Intent(IntentName.HELP, 1.0, {})

    if normalized in {"open chrome", "start chrome", "launch chrome"}:
        return Intent(IntentName.LAUNCH_APP, 1.0, {"app_name": "chrome"})

    if normalized.startswith("open folder"):
        folder = text.strip()[len("open folder") :].strip() or "."
        return Intent(IntentName.LIST_DIR, 0.95, {"path": folder})

    section_match = re.search(
        r"(?:show|open|read|find|go to).*?(?:section|part)\s+(?:called\s+|named\s+)?(.+?)\s+(https?://\S+)",
        text.strip(),
        re.IGNORECASE,
    ) or re.search(
        r"(?:show|open|read|find|go to).*?\b(.+?)\s+(?:section|part)\s+(https?://\S+)",
        text.strip(),
        re.IGNORECASE,
    )
    if section_match:
        section_name = section_match.group(1).strip()
        section_name = re.sub(r"^(?:me\s+)?(?:the\s+)?", "", section_name, flags=re.IGNORECASE)
        return Intent(
            IntentName.OPEN_SECTION,
            0.98,
            {"section": section_name, "url": section_match.group(2).rstrip(".,;!?" )},
        )

    if re.search(
        r"\b(?:compare|popular|best|recommend|which one|what should i buy|buy|options|top)\b|तुलना|बेहतर",
        normalized,
    ) and re.search(r"\b(?:products?|cards?|gpu|graphics|phones?|laptops?|headphones|camera|monitor)\b|फोन|लैपटॉप", normalized):
        return Intent(IntentName.RESEARCH_WEB, 0.92, {"query": text.strip(), "max_sources": "3"})

    for prefix in ("search the web for ", "search google for ", "search for ", "look up ", "google ", "search "):
        if normalized.startswith(prefix):
            query = text.strip()[len(prefix) :].strip()
            if query:
                return Intent(IntentName.SEARCH_WEB, 0.95, {"query": query})

    for prefix in ("tell me about ", "what's the news on ", "what is the latest news on ", "what's the latest news on "):
        if normalized.startswith(prefix):
            query = text.strip()[len(prefix) :].strip()
            if query:
                return Intent(IntentName.SEARCH_WEB, 0.9, {"query": query})

    return None
