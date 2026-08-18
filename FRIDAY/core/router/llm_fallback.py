from __future__ import annotations

import json
import asyncio

from core.events.bus import EventBus
from core.events.event_types import EventType
from core.events.models import Event
from core.llm.ollama_client import OllamaClient, LlmResponse, parse_llm_response
from core.llm.streaming_worker import StreamingLlmWorker
from core.memory.command_history import CommandHistory
from core.router.rules import Intent, IntentName


SYSTEM_PROMPT = """You are the reasoning module for FRIDAY.
Respond ONLY with a valid JSON object. No explanations outside JSON.
Available intents: {available_intents}, chat.

If the user is greeting, chatting, or asking a general question with no clear system action (like restarting a worker or checking status), the intent MUST be 'chat', not 'help' or any other tool name.

Examples:
User Input: hi
{"intent": "chat", "confidence": 1.0, "suggested_action": "", "reasoning_summary": "Greeting.", "parameters": {}}

User Input: give in depth knowledge about the jarvis
{"intent": "chat", "confidence": 0.9, "suggested_action": "", "reasoning_summary": "General question.", "parameters": {}}

User Input: search google for latest news
{"intent": "search_web", "confidence": 0.9, "suggested_action": "", "reasoning_summary": "Web search request.", "parameters": {"query": "latest news"}}
"""


class LlmFallbackRouter:
    def __init__(
        self,
        ollama_client: OllamaClient | None = None,
        command_history: CommandHistory | None = None,
        event_bus: EventBus | None = None,
        streaming_worker: StreamingLlmWorker | None = None,
        valid_tools: list[str] | None = None,
    ) -> None:
        self.ollama = ollama_client or OllamaClient()
        self.history = command_history or CommandHistory()
        self.event_bus = event_bus
        self.streaming_worker = streaming_worker
        self.valid_tools = valid_tools or []

    async def route(self, text: str, context: list[dict[str, str]] | None = None, correlation_id: str | None = None, personality_instructions: str = "") -> Intent:
        await self._emit(EventType.LLM_REQUEST_SENT, {"model": self.ollama.model, "prompt_preview": text[:100]}, correlation_id)

        try:
            raw_response, metrics = await self.ollama.generate(self._build_prompt(text, personality_instructions), max_tokens=80)
        except Exception as e:
            import traceback
            print(f"\n\n[DIAGNOSTIC] ollama.generate THREW EXCEPTION: {repr(e)}")
            traceback.print_exc()
            await self._emit(EventType.LLM_FAILURE, {"error": str(e), "model": self.ollama.model}, correlation_id)
            return self._fallback(text)

        if not metrics.success:
            print(f"\n\n[DIAGNOSTIC] ollama.generate FAILED METRICS: {metrics.error}")
            await self._emit(EventType.LLM_FAILURE, {"error": metrics.error or "unknown", "model": metrics.model}, correlation_id)
            return self._fallback(text)

        parsed = parse_llm_response(raw_response or "")
        if not parsed:
            print(f"\n\n[DIAGNOSTIC] PARSE FAILED. RAW RESPONSE: {repr(raw_response)}")
            await self._emit(EventType.LLM_FAILURE, {"error": "malformed_response", "model": self.ollama.model}, correlation_id)
            return self._fallback(text)

        await self._emit(EventType.LLM_RESPONSE_RECEIVED, {"intent": parsed.intent, "confidence": parsed.confidence, "latency": metrics.latency_seconds}, correlation_id)

        try:
            intent_name = IntentName(parsed.intent)
        except ValueError:
            # We can still check if it's a valid tool even if it's not in IntentName
            # because IntentName is an outdated enum. We'll force it to lowercase string for checks.
            pass
            
        intent_str = parsed.intent.lower()
        if intent_str != "chat" and intent_str not in self.valid_tools:
            print(f"[DIAGNOSTIC] Tool '{intent_str}' not found in valid_tools. Falling back to chat.")
            intent_str = "chat"
            
        # Re-assign intent_name to IntentName.CHAT if it was forced to chat
        try:
            intent_name = IntentName(intent_str)
        except ValueError:
            intent_name = IntentName.UNKNOWN
            # We'll just pass the raw string if we want, but the dataclass Intent requires IntentName.
            # Actually, the dataclass Intent requires an IntentName Enum.
            # If it's a valid tool but not in IntentName Enum, we might have a type issue.
            pass

        parameters: dict = {}
        try:
            parameters = json.loads(raw_response or "{}").get("parameters", {})
        except Exception:
            pass

        chat_response_text = ""
        if intent_name == IntentName.CHAT:
            if self.streaming_worker:
                try:
                    context_str = ""
                    if context:
                        context_str = "\n".join(f"{c['role'].capitalize()}: {c['content']}" for c in context[:-1])
                        if context_str:
                            context_str += f"\nUser: {text}\nResponse:"
                        else:
                            context_str = f"User: {text}\nResponse:"
                    else:
                        context_str = f"User: {text}\nResponse:"
                    streamed = await self.streaming_worker.stream_reasoning(context_str.strip(), correlation_id)
                    if streamed:
                        chat_response_text = streamed
                except Exception:
                    pass
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
