import logging
from unittest.mock import AsyncMock, MagicMock
import pytest

from core.llm.local_llm_client import LlmRequestMetrics
from core.router.llm_fallback import LlmFallbackRouter


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
