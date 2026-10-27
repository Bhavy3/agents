from __future__ import annotations

import logging
logger = logging.getLogger(__name__)

ROUTER_LLM_TIMEOUT_SECONDS = 12.0

import json
import re
import asyncio
from typing import Any

from core.events.bus import EventBus
from core.events.event_types import EventType
from core.events.models import Event
from core.llm.ollama_client import OllamaClient, LlmResponse, parse_llm_response
from core.llm.streaming_worker import StreamingLlmWorker
from core.memory.command_history import CommandHistory
from core.memory.explicit_requests import (
    EXPLICIT_MEMORY_REQUEST as _EXPLICIT_MEMORY_REQUEST,
    extract_explicit_memory_content,
)
from core.router.adaptive_router import AdaptiveRouter
from core.router.rules import Intent, IntentName


SYSTEM_PROMPT = """You are the reasoning module for FRIDAY.
Respond ONLY with a valid JSON object. No explanations outside JSON.
Available intents: {available_intents}, chat.

If the user is greeting, chatting, or asking a general question with no clear system action (like restarting a worker or checking status), the intent MUST be 'chat', not 'help' or any other tool name.
If the user asks for a simple lookup, use 'search_web' with a concise query. If the user asks to compare products, find popular/best options, recommend what to buy, or research a topic across sources, use 'research_web' with the original question as the query. If the user asks to show/open/read a named section of a specific URL, use 'open_section' with parameters {"url": "...", "section": "..."}. Use 'open_url' only when the user explicitly asks to open or launch a website in the browser.

Examples:
User Input: hi
{"intent": "chat", "confidence": 1.0, "suggested_action": "", "reasoning_summary": "Greeting.", "parameters": {}}

User Input: give in depth knowledge about the jarvis
{"intent": "chat", "confidence": 0.9, "suggested_action": "", "reasoning_summary": "General question.", "parameters": {}}

User Input: search google for latest news
{"intent": "search_web", "confidence": 0.9, "suggested_action": "", "reasoning_summary": "Web search request.", "parameters": {"query": "latest news"}}

User Input: compare several products and recommend one using evidence
{"intent": "research_web", "confidence": 0.9, "suggested_action": "", "reasoning_summary": "Multi-source product research.", "parameters": {"query": "compare products and recommend one using evidence", "max_sources": 3}}
"""


def _extract_parameters(raw_response: str) -> dict:
    raw = (raw_response or "").strip()

    # 0. Strip markdown fences: if the text contains ```json or ```, take the content between the first pair of fences, then strip whitespace.
    text = raw
    if "```json" in text:
        start = text.index("```json") + 7
        end = text.find("```", start)
        if end != -1:
            text = text[start:end].strip()
        else:
            text = text[start:].strip()
    elif "```" in text:
        start = text.index("```") + 3
        end = text.find("```", start)
        if end != -1:
            text = text[start:end].strip()
        else:
            text = text[start:].strip()

    initial_error: Exception | None = None

    # 1. Strict json.loads. If the result is a dict: return result["parameters"] if it is a dict, else {}.
    try:
        result = json.loads(text)
        if isinstance(result, dict):
            params = result.get("parameters")
            return params if isinstance(params, dict) else {}
    except (json.JSONDecodeError, ValueError) as e:
        initial_error = e

    # 2. If the stripped text ends with ")", replace that final character with "}" and parse again, using the same rule as tier 1.
    trimmed = text.rstrip()
    if trimmed.endswith(")"):
        repaired = trimmed[:-1] + "}"
        try:
            result = json.loads(repaired)
            if isinstance(result, dict):
                params = result.get("parameters")
                return params if isinstance(params, dict) else {}
        except (json.JSONDecodeError, ValueError):
            logger.warning("llm_parameter_repair_parse_failed", exc_info=True)

    # 3. Regex: r'"parameters"\s*:\s*(\{(?:[^{}"]|"(?:\\.|[^"\\])*")*\})'
    match = re.search(r'"parameters"\s*:\s*(\{(?:[^{}"]|"(?:\\.|[^"\\])*")*\})', text)
    if match:
        try:
            params = json.loads(match.group(1))
            if isinstance(params, dict):
                return params
        except (json.JSONDecodeError, ValueError):
            logger.warning("llm_parameter_regex_parse_failed", exc_info=True)

    # 4. Otherwise: logger.error("llm_parameters_unrecoverable", extra={"raw_response": raw}, exc_info=initial_error) and return {}.
    # A small local model often reaches its token limit after emitting the
    # intent and the beginning of a query. Recover that query value when the
    # outer JSON is incomplete; the caller still replaces it with the user's
    # original text when recovery is not trustworthy.
    query_match = re.search(r'"query"\s*:\s*"((?:\\.|[^"\\])*)', text, re.DOTALL)
    if query_match:
        try:
            recovered = json.loads('"' + query_match.group(1) + '"')
        except (json.JSONDecodeError, ValueError):
            recovered = query_match.group(1).rstrip(" ,}]\n\r\t")
        if recovered.strip():
            return {"query": recovered}

    if initial_error is None:
        initial_error = ValueError("Could not parse parameters as dictionary from LLM response")
    logger.error("llm_parameters_unrecoverable", extra={"raw_response": raw}, exc_info=initial_error)
    return {}


class LlmFallbackRouter:
    def __init__(
        self,
        ollama_client: OllamaClient | None = None,
        command_history: CommandHistory | None = None,
        event_bus: EventBus | None = None,
        streaming_worker: StreamingLlmWorker | None = None,
        valid_tools: list[str] | None = None,
        model_manager: Any | None = None,
    ) -> None:
        self.ollama = ollama_client or OllamaClient()
        self.history = command_history or CommandHistory()
        self.event_bus = event_bus
        self.streaming_worker = streaming_worker
        self.valid_tools = valid_tools or []
        self.adaptive_router = AdaptiveRouter(model_manager=model_manager) if model_manager is not None else None

    async def route(self, text: str, context: list[dict[str, str]] | None = None, correlation_id: str | None = None, personality_instructions: str = "", chat_instructions: str = "") -> Intent:
        if self.adaptive_router is not None:
            await self.adaptive_router.route(text)
        await self._emit(EventType.LLM_REQUEST_SENT, {"model": self.ollama.model, "prompt_preview": text[:100]}, correlation_id)

        try:
            raw_response, metrics = await asyncio.wait_for(
                self.ollama.generate(self._build_prompt(text, personality_instructions), max_tokens=80),
                timeout=ROUTER_LLM_TIMEOUT_SECONDS,
            )
        except Exception as e:
            logger.exception("router_llm_generate_failed", extra={"model": self.ollama.model})
            await self._emit(EventType.LLM_FAILURE, {"error": str(e), "model": self.ollama.model}, correlation_id)
            return self._fallback(text)

        if not metrics.success:
            logger.error("router_llm_generation_unsuccessful", extra={"error": metrics.error, "model": metrics.model})
            await self._emit(EventType.LLM_FAILURE, {"error": metrics.error or "unknown", "model": metrics.model}, correlation_id)
            return self._fallback(text)

        parsed = parse_llm_response(raw_response or "")
        if not parsed:
            logger.warning("router_llm_response_parse_failed", extra={"raw_response": raw_response})
            await self._emit(EventType.LLM_FAILURE, {"error": "malformed_response", "model": self.ollama.model}, correlation_id)
            return self._fallback(text)

        await self._emit(EventType.LLM_RESPONSE_RECEIVED, {"intent": parsed.intent, "confidence": parsed.confidence, "latency": metrics.latency_seconds}, correlation_id)

        intent_str = parsed.intent.strip().lower()
        if intent_str == "remember" and extract_explicit_memory_content(text) is None:
            logger.warning("remember_intent_rejected", extra={"raw_value": parsed.intent})
            intent_str = "chat"

        try:
            intent_name = IntentName(intent_str)
        except ValueError:
            logger.warning("intent_enum_mismatch", extra={"raw_value": intent_str})
            intent_name = IntentName.CHAT
            intent_str = "chat"

        if intent_name == IntentName.UNKNOWN:
            logger.warning("unknown_intent_rejected", extra={"raw_value": parsed.intent})
            intent_name = IntentName.CHAT
            intent_str = "chat"

        if intent_str != "chat" and intent_str not in self.valid_tools:
            logger.warning("router_tool_unavailable_falling_back_to_chat", extra={"intent": intent_str})
            intent_str = "chat"
            intent_name = IntentName.CHAT

        parameters = _extract_parameters(raw_response or "")

        if intent_name in {IntentName.SEARCH_WEB, IntentName.RESEARCH_WEB}:
            # Never let truncated router JSON erase the user's actual search
            # request. This also keeps the tool call valid when the model only
            # emitted intent/confidence before hitting max_tokens.
            query = parameters.get("query")
            if not isinstance(query, str) or not query.strip():
                parameters["query"] = text.strip()
            if intent_name == IntentName.RESEARCH_WEB:
                parameters.setdefault("max_sources", 3)

        chat_response_text = ""
        if intent_name == IntentName.CHAT:
            if self.streaming_worker:
                try:
                    context_str = chat_instructions + "\n\n" if chat_instructions else ""
                    if context:
                        history_str = "\n".join(f"{c['role'].capitalize()}: {c['content']}" for c in context[:-1])
                        if history_str:
                            context_str += history_str + f"\nUser: {text}\nResponse:"
                        else:
                            context_str += f"User: {text}\nResponse:"
                    else:
                        context_str += f"User: {text}\nResponse:"
                    streamed = await self.streaming_worker.stream_reasoning(context_str.strip(), correlation_id)
                    if streamed:
                        chat_response_text = streamed
                    else:
                        chat_response_text = "I’m still processing that. Please give me a moment and try again."
                except Exception as e:
                    logger.error("llm_fallback_streaming_error", extra={"error": str(e)}, exc_info=True)
                    chat_response_text = "I hit a temporary processing issue. Please try again in a moment."
            parameters["response_text"] = chat_response_text
        return Intent(name=intent_name, confidence=parsed.confidence, parameters=parameters, source="ollama_reasoning")

    def _build_prompt(self, text: str, personality_instructions: str = "") -> str:
        history = "\n".join(f"User: {h.command} -> {h.success}" for h in self.history.recent()[-5:])
        intents_str = ", ".join(self.valid_tools) if self.valid_tools else "open_url, search_web"
        prompt = SYSTEM_PROMPT.replace("{available_intents}", intents_str)
        return f"{prompt}\n{personality_instructions}\n\nHistory:\n{history}\n\nUser Input: {text}\n\nJSON:"

    def _fallback(self, text: str) -> Intent:
        return Intent(name=IntentName.CHAT, confidence=0.1, parameters={"response_text": "I encountered an error trying to process that. Could you try again?"}, source="llm_fallback_error")

    async def _emit(self, event_type: EventType, payload: dict, correlation_id: str | None) -> None:
        if self.event_bus:
            await self.event_bus.publish(Event.create(event_type, payload, "llm_router", correlation_id))
