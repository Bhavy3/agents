from unittest.mock import AsyncMock

import pytest

from core.events.bus import EventBus
from core.events.event_types import EventType
from core.events.models import Event
from core.orchestrator.conversation import OrchestratorWorker
from core.router.intent_router import IntentRouter
from core.router.llm_fallback import LlmFallbackRouter
from core.router.rules import FAST_CHAT_SOURCE, Intent, IntentName


@pytest.mark.asyncio
async def test_clear_chat_uses_local_fast_path_and_ambiguous_text_keeps_classifier():
    fallback = AsyncMock(spec=LlmFallbackRouter)
    fallback.route.return_value = Intent(IntentName.CHAT, 0.8, {}, source="ollama_reasoning")
    router = IntentRouter(event_bus=None, llm_fallback=fallback)  # type: ignore[arg-type]

    fast_intent = await router.route("What is 2 + 2?")
    assert fast_intent.name is IntentName.CHAT
    assert fast_intent.source == FAST_CHAT_SOURCE
    fallback.route.assert_not_awaited()

    ambiguous_intent = await router.route("Can you open Chrome?")
    assert ambiguous_intent.source == "ollama_reasoning"
    fallback.route.assert_awaited_once()

    why_intent = await router.route("Why do leaves change color?")
    assert why_intent.name is IntentName.CHAT
    assert why_intent.source == FAST_CHAT_SOURCE
    fallback.route.assert_awaited_once()


@pytest.mark.asyncio
async def test_fast_chat_streams_once_with_safe_chat_prompt_and_is_observable():
    bus = EventBus()
    await bus.start()

    stream = AsyncMock()
    stream.stream_reasoning.return_value = "Four."
    stream.set_model = lambda *_args: None
    router = AsyncMock()
    router.route.return_value = Intent(IntentName.CHAT, 1.0, {}, source=FAST_CHAT_SOURCE)

    orchestrator = OrchestratorWorker(bus, router, stream)
    orchestrator._request_memory_context = AsyncMock(return_value="- User prefers concise answers")
    orchestrator.response_gate.wait_for_readiness = AsyncMock(return_value=True)
    orchestrator.adaptive_router.route = AsyncMock(return_value=("3b", "simple_query_fast"))

    responses: list[Event] = []

    async def collect_response(event: Event) -> None:
        responses.append(event)

    bus.subscribe(EventType.RESPONSE_READY, collect_response)

    try:
        await orchestrator._initiate_turn("What is 2 + 2?", "fast-correlation", typed_input=True)
        assert orchestrator._routing_task is not None
        await orchestrator._routing_task
        await bus.drain()

        router.route.assert_not_awaited()
        orchestrator._request_memory_context.assert_not_awaited()
        orchestrator.response_gate.wait_for_readiness.assert_not_awaited()
        stream.stream_reasoning.assert_awaited_once()
        prompt = stream.stream_reasoning.await_args.args[0]
        assert "Answer accurately and concisely." in prompt
        assert "Do not claim to remember information" in prompt
        assert "System Memory/Context:" not in prompt
        assert "User: What is 2 + 2?" in prompt
        assert [event.payload["text"] for event in responses] == ["Four."]
    finally:
        await bus.stop()


@pytest.mark.asyncio
async def test_fast_chat_does_not_route_explicit_web_search():
    fallback = AsyncMock(spec=LlmFallbackRouter)
    router = IntentRouter(event_bus=None, llm_fallback=fallback)  # type: ignore[arg-type]

    intent = await router.route("Search for the latest Python release")

    assert intent.name is IntentName.SEARCH_WEB
    assert intent.source == "rules"
    fallback.route.assert_not_awaited()


@pytest.mark.asyncio
async def test_dynamic_factual_lookup_still_uses_classifier():
    fallback = AsyncMock(spec=LlmFallbackRouter)
    fallback.route.return_value = Intent(IntentName.SEARCH_WEB, 0.9, {"query": "most recent FIFA World Cup"})
    router = IntentRouter(event_bus=None, llm_fallback=fallback)  # type: ignore[arg-type]

    intent = await router.route("Who won the most recent FIFA World Cup?")

    assert intent.name is IntentName.SEARCH_WEB
    fallback.route.assert_awaited_once()


@pytest.mark.asyncio
async def test_static_factual_lookup_with_web_signal_keeps_classifier_path():
    fallback = AsyncMock(spec=LlmFallbackRouter)
    fallback.route.return_value = Intent(IntentName.SEARCH_WEB, 0.9, {"query": "capital of Australia"})
    router = IntentRouter(event_bus=None, llm_fallback=fallback)  # type: ignore[arg-type]

    intent = await router.route("What is the capital of Australia?")

    assert intent.name is IntentName.SEARCH_WEB
    fallback.route.assert_awaited_once()
