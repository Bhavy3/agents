"""Shared response types and parsing for local LLM providers."""

import json
import logging
from dataclasses import dataclass
from enum import StrEnum

logger = logging.getLogger(__name__)


class LlmProvider(StrEnum):
    OLLAMA = "ollama"
    LLAMACPP = "llamacpp"


@dataclass(slots=True, frozen=True)
class LlmResponse:
    intent: str
    confidence: float
    suggested_action: str
    reasoning_summary: str


@dataclass(slots=True, frozen=True)
class LlmRequestMetrics:
    prompt_tokens: int = 0
    response_tokens: int = 0
    latency_seconds: float = 0.0
    model: str = ""
    success: bool = False
    error: str | None = None


def parse_llm_response(raw_text: str) -> LlmResponse | None:
    text = raw_text.strip()
    if "```json" in text:
        start = text.index("```json") + 7
        end = text.index("```", start)
        text = text[start:end].strip()
    elif "```" in text:
        start = text.index("```") + 3
        end = text.index("```", start)
        text = text[start:end].strip()

    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        import re
        intent_match = re.search(r'"intent"\s*:\s*"([^"]+)"', text)
        confidence_match = re.search(r'"confidence"\s*:\s*([\d\.]+)', text)
        if intent_match and confidence_match:
            try:
                return LlmResponse(
                    intent=intent_match.group(1),
                    confidence=float(confidence_match.group(1)),
                    suggested_action="",
                    reasoning_summary="[Truncated]"
                )
            except ValueError:
                logger.warning("llm_response_confidence_invalid", exc_info=True)
        return None

    if not isinstance(data, dict):
        return None

    required = {"intent", "confidence"}
    if not required.issubset(data.keys()):
        return None

    try:
        return LlmResponse(
            intent=str(data["intent"]),
            confidence=float(data["confidence"]),
            suggested_action=str(data.get("suggested_action", "")),
            reasoning_summary=str(data.get("reasoning_summary", "")),
        )
    except (TypeError, ValueError):
        return None


def resolve_llm_provider(base_url: str, explicit: str | None = None) -> LlmProvider:
    if explicit:
        value = explicit.strip().lower()
        if value in {"ollama", "llamacpp", "llama_cpp", "llama.cpp"}:
            return LlmProvider.OLLAMA if value == "ollama" else LlmProvider.LLAMACPP
    if ":11434" in base_url or "localhost:11434" in base_url:
        return LlmProvider.OLLAMA
    return LlmProvider.LLAMACPP
