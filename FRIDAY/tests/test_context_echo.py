import pytest
import asyncio
from unittest.mock import AsyncMock

from core.router.llm_fallback import LlmFallbackRouter
from core.events.bus import EventBus

@pytest.mark.asyncio
async def test_llm_fallback_no_echo():
    bus = EventBus()
    await bus.start()
    
    mock_ollama = AsyncMock()
    # Mocking classification response to simulate a parse failure (truncate JSON)
    mock_ollama.generate.return_value = ("{ \"intent\": \"chat\", \"confidence\": 0.9, \"response_", AsyncMock(success=True, latency_seconds=0.1))
    
    mock_streaming = AsyncMock()
    mock_streaming.stream_reasoning.return_value = "This is a streamed reply."
    
    router = LlmFallbackRouter(
        ollama_client=mock_ollama,
        command_history=None,
        event_bus=bus,
        streaming_worker=mock_streaming,
    )
    
    text = "i am making the jarvis like system bro"
    # Execute route with simulated failure
    intent = await router.route(text)
    
    # Assert we did NOT get the exact text back as response_text
    assert intent.name.value == "chat"
    # On fallback, response_text should be our hardcoded error, NOT the input text
    assert intent.parameters.get("response_text") != text
    assert intent.parameters.get("text") is None  # 'text' should not be leaked into parameters
    
    await bus.stop()
    
    
@pytest.mark.asyncio
async def test_llm_fallback_context_passed_to_stream():
    bus = EventBus()
    await bus.start()
    
    mock_ollama = AsyncMock()
    # Mocking a successful JSON response
    mock_ollama.generate.return_value = ('{ "intent": "chat", "confidence": 0.9, "response_text": "" }', AsyncMock(success=True, latency_seconds=0.1))
    
    mock_streaming = AsyncMock()
    mock_streaming.stream_reasoning.return_value = "This is a streamed reply."
    
    router = LlmFallbackRouter(
        ollama_client=mock_ollama,
        command_history=None,
        event_bus=bus,
        streaming_worker=mock_streaming,
    )
    
    text = "What do you think?"
    context = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "Hi there!"},
        {"role": "user", "content": text},
    ]
    
    intent = await router.route(text, context=context)
    
    # Verify the streaming worker received the formatted context
    mock_streaming.stream_reasoning.assert_called_once()
    args, _ = mock_streaming.stream_reasoning.call_args
    passed_context = args[0]
    
    assert "User: hello" in passed_context
    assert "Assistant: Hi there!" in passed_context
    assert f"User: {text}" in passed_context
    
    await bus.stop()
