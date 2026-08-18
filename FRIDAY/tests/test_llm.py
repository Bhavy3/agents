import asyncio
import pytest
from unittest.mock import MagicMock, patch
from core.events.bus import EventBus
from core.events.event_types import EventType
from core.llm.ollama_client import OllamaClient, parse_llm_response
from core.router.llm_fallback import LlmFallbackRouter
from core.router.rules import IntentName

def test_parse_llm_response_valid():
    raw = '{"intent": "help", "confidence": 0.9, "response_text": "How can I help?", "suggested_action": "show_help", "reasoning_summary": "User asked for help"}'
    parsed = parse_llm_response(raw)
    assert parsed is not None
    assert parsed.intent == "help"
    assert parsed.confidence == 0.9

def test_parse_llm_response_markdown_json():
    raw = 'Sure! Here is the response:\n```json\n{"intent": "chat", "confidence": 1.0, "response_text": "Hello!"}\n```'
    parsed = parse_llm_response(raw)
    assert parsed is not None
    assert parsed.intent == "chat"

def test_parse_llm_response_invalid():
    assert parse_llm_response("not json") is None
    assert parse_llm_response('{"wrong": "format"}') is None

@pytest.mark.asyncio
async def test_llm_fallback_router_handles_failure():
    # Use a dummy metrics object
    class DummyMetrics:
        success = False
        error = "timeout"
        model = "test-model"
        latency_seconds = 0.0

    with patch("core.llm.ollama_client.OllamaClient.generate") as mock_gen:
        mock_gen.return_value = (None, DummyMetrics())
        
        router = LlmFallbackRouter()
        intent = await router.route("hello")
        
        assert intent.name == IntentName.CHAT
        assert intent.source == "llm_fallback_error"

@pytest.mark.asyncio
async def test_llm_fallback_router_emits_events():
    bus = EventBus()
    await bus.start()
    
    events = []
    async def track(e):
        events.append(e)
    
    bus.subscribe_all(track)
    
    class DummyMetrics:
        success = True
        latency_seconds = 0.5
        model = "test-model"
        error = None

    with patch("core.llm.ollama_client.OllamaClient.generate") as mock_gen:
        mock_gen.return_value = ('{"intent": "help", "confidence": 0.9, "response_text": "Help!"}', DummyMetrics())
        
        router = LlmFallbackRouter(event_bus=bus)
        await router.route("help me")
        
    await bus.drain()
    await bus.stop()
    
    event_types = [e.event_type for e in events]
    assert EventType.LLM_REQUEST_SENT in event_types
    assert EventType.LLM_RESPONSE_RECEIVED in event_types

@pytest.mark.asyncio
async def test_health_check_ttl_caching():
    from core.llm.local_llm_client import LocalLLMClient, LlmProvider
    
    client = LocalLLMClient(provider=LlmProvider.LLAMACPP)
    
    # First call - mock HTTP get
    with patch("httpx.AsyncClient.get") as mock_get:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_get.return_value = mock_response
        
        result1 = await client.health_check()
        assert result1 is True
        assert mock_get.call_count == 1
        
    # Second call - should hit TTL cache, NO HTTP get should be made
    with patch("httpx.AsyncClient.get") as mock_get_2:
        result2 = await client.health_check()
        assert result2 is True
        assert mock_get_2.call_count == 0
        
    await client.aclose()