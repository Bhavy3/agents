from __future__ import annotations

import uuid

from core.events.bus import EventBus
from core.events.event_types import EventType
from core.events.models import Event
from core.logging.logger import get_logger
from core.router.llm_fallback import LlmFallbackRouter
from core.router.rules import Intent, route_by_rules


class IntentRouter:
    def __init__(self, event_bus: EventBus, llm_fallback: LlmFallbackRouter | None = None) -> None:
        self.event_bus = event_bus
        self.llm_fallback = llm_fallback or LlmFallbackRouter()
        self.name = "intent_router"
        self.logger = get_logger("router.intent")

    async def start(self) -> None:
        self.logger.info("intent_router_ready_for_orchestrator")

    async def handle_user_text(self, event: Event, personality_instructions: str = "") -> None:
        text = str(event.payload.get("text", "")).strip()
        intent = await self.route(text, correlation_id=event.correlation_id, personality_instructions=personality_instructions)
        if intent.name.value == "chat":
            return
        action_id = str(uuid.uuid4())
        await self.event_bus.publish(
            Event.create(
                EventType.ACTION_REQUESTED,
                {
                    "action_id": action_id,
                    "intent": intent.name.value,
                    "parameters": intent.parameters,
                },
                self.name,
                event.correlation_id,
            )
        )

    async def route(self, text: str, context: list[dict[str, str]] | None = None, correlation_id: str | None = None, personality_instructions: str = "", chat_instructions: str = "") -> Intent:
        rule_intent = route_by_rules(text)
        if rule_intent is not None:
            return rule_intent
        return await self.llm_fallback.route(text, context=context, correlation_id=correlation_id, personality_instructions=personality_instructions, chat_instructions=chat_instructions)
