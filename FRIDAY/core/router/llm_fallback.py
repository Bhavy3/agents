from __future__ import annotations

import json

from core.events.bus import EventBus
from core.events.event_types import EventType
from core.events.models import Event
from core.llm.ollama_client import OllamaClient, LlmResponse, parse_llm_response
from core.llm.streaming_worker import StreamingLlmWorker
from core.memory.command_history import CommandHistory
from core.router.rules import Intent, IntentName


SYSTEM_PROMPT = """You are the reasoning module for FRIDAY.
Respond ONLY with a valid JSON object. No explanations outside JSON.
Available intents: open_chrome, open_folder, search_google, help, exit, chat.

{
  "intent": "intent_name",
  "confidence": 0.9,
  "response_text": "Brief reply.",
  "suggested_action": "action:detail",
  "reasoning_summary": "Why this intent.",
  "parameters": {}
}"""


class LlmFallbackRouter:
    def __init__(
        self,
        ollama_client: OllamaClient | None = None,
        command_history: CommandHistory | None = None,
        event_bus: EventBus | None = None,
        streaming_worker: StreamingLlmWorker | None = None,
    ) -> None:
        self.ollama = ollama_client or OllamaClient()
        self.history = command_history or CommandHistory()
        self.event_bus = event_bus
        self.streaming_worker = streaming_worker

    async def route(self, text: str, correlation_id: str | None = None, personality_instructions: str = "") -> Intent:
        await self._emit(EventType.LLM_REQUEST_SENT, {"model": self.ollama.model, "prompt_preview": text[:100]}, correlation_id)

        raw_response, metrics = await self.ollama.generate(self._build_prompt(text, personality_instructions))

        if not metrics.success:
            await self._emit(EventType.LLM_FAILURE, {"error": metrics.error or "unknown", "model": metrics.model}, correlation_id)
            return self._fallback(text)

        parsed = parse_llm_response(raw_response or "")
        if not parsed:
            await self._emit(EventType.LLM_FAILURE, {"error": "malformed_response", "model": self.ollama.model}, correlation_id)
            return self._fallback(text)

        await self._emit(EventType.LLM_RESPONSE_RECEIVED, {"intent": parsed.intent, "confidence": parsed.confidence, "latency": metrics.latency_seconds}, correlation_id)

        try:
            intent_name = IntentName(parsed.intent)
        except ValueError:
            intent_name = IntentName.CHAT

        parameters: dict = {}
        try:
            parameters = json.loads(raw_response or "{}").get("parameters", {})
        except Exception:
            pass

        # For chat intents, use streaming if available for a richer response
        if intent_name == IntentName.CHAT and self.streaming_worker:
            streamed = await self.streaming_worker.stream_reasoning(f"User: {text}\nResponse:", correlation_id)
            if streamed:
                parsed = LlmResponse(parsed.intent, parsed.confidence, streamed, parsed.suggested_action, parsed.reasoning_summary)

        if intent_name == IntentName.CHAT and "text" not in parameters:
            parameters["text"] = text

        return Intent(name=intent_name, confidence=parsed.confidence, parameters=parameters, source="ollama_reasoning")

    def _build_prompt(self, text: str, personality_instructions: str = "") -> str:
        history = "\n".join(f"User: {h.command} -> {h.success}" for h in self.history.recent()[-5:])
        return f"{SYSTEM_PROMPT}\n{personality_instructions}\n\nHistory:\n{history}\n\nUser Input: {text}\n\nJSON:"

    def _fallback(self, text: str) -> Intent:
        return Intent(name=IntentName.CHAT, confidence=0.1, parameters={"text": text}, source="llm_fallback_error")

    async def _emit(self, event_type: EventType, payload: dict, correlation_id: str | None) -> None:
        if self.event_bus:
            await self.event_bus.publish(Event.create(event_type, payload, "llm_router", correlation_id))
