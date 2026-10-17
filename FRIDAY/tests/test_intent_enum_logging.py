import logging
from unittest.mock import AsyncMock, MagicMock
import pytest

from core.llm.local_llm_client import LlmRequestMetrics
from core.router.llm_fallback import LlmFallbackRouter
from core.router.rules import IntentName


def _mock_router(intent: str, *, parameters: str = "{}") -> LlmFallbackRouter:
    mock_client = MagicMock()
    mock_client.model = "test-model"
    mock_client.generate = AsyncMock(
        return_value=(
            f'{{"intent": "{intent}", "confidence": 0.9, "parameters": {parameters}}}',
            LlmRequestMetrics(success=True, model="test-model"),
        )
    )
    return LlmFallbackRouter(
        ollama_client=mock_client,
        valid_tools=["remember", "search_web"],
    )


@pytest.mark.asyncio
async def test_intent_enum_mismatch_warning(caplog):
    mock_client = MagicMock()
    mock_client.model = "test-model"
    mock_client.generate = AsyncMock(
        return_value=(
            '{"intent": "not_a_real_intent", "confidence": 0.9, "suggested_action": "", "reasoning_summary": "", "parameters": {}}',
            LlmRequestMetrics(success=True, model="test-model"),
        )
    )

    router = LlmFallbackRouter(ollama_client=mock_client)
    with caplog.at_level(logging.WARNING):
        await router.route("test prompt")

    records = [
        r for r in caplog.records
        if r.levelname == "WARNING" and (r.msg == "intent_enum_mismatch" or r.getMessage() == "intent_enum_mismatch")
    ]
    assert len(records) == 1
    assert getattr(records[0], "raw_value", None) == "not_a_real_intent"


@pytest.mark.asyncio
async def test_remember_classification_for_regular_question_falls_back_to_chat():
    router = _mock_router("remember", parameters='{"fact": "2 + 2 is 4"}')

    intent = await router.route("What is 2 + 2?")

    assert intent.name == IntentName.CHAT


@pytest.mark.asyncio
async def test_unknown_intent_falls_back_to_chat_instead_of_unknown_action():
    router = _mock_router("not_a_real_intent")

    intent = await router.route("Tell me something")

    assert intent.name == IntentName.CHAT


@pytest.mark.asyncio
async def test_unknown_sentinel_cannot_be_enabled_as_a_tool():
    router = _mock_router("unknown")
    router.valid_tools.append("unknown")

    intent = await router.route("Tell me something")

    assert intent.name == IntentName.CHAT


@pytest.mark.asyncio
async def test_explicit_remember_and_known_tool_routing_are_preserved():
    remember_router = _mock_router("remember", parameters='{"fact": "my favorite color is blue"}')
    remember_intent = await remember_router.route("Remember that my favorite color is blue.")

    search_router = _mock_router("search_web", parameters='{"query": "latest local news"}')
    search_intent = await search_router.route("Search for the latest local news")

    assert remember_intent.name == IntentName.REMEMBER
    assert search_intent.name == IntentName.SEARCH_WEB
    assert search_intent.parameters == {"query": "latest local news"}
