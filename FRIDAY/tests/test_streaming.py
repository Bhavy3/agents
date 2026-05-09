import asyncio
import pytest
from unittest.mock import MagicMock, patch
from core.events.bus import EventBus
from core.events.event_types import EventType
from core.llm.ollama_client import OllamaClient
from core.llm.stream_aggregator import ResponseAggregator
from core.llm.streaming_worker import StreamingLlmWorker

@pytest.mark.asyncio
async def test_stream_aggregation_success():
    bus = EventBus()
    await bus.start()
    agg = ResponseAggregator(bus)
    
    stream_id = await agg.start_stream("test-model")
    await agg.add_chunk(stream_id, "Hello ")
    await agg.add_chunk(stream_id, "world!")
    full_text = await agg.complete_stream(stream_id)
    
    assert full_text == "Hello world!"
    await bus.drain()
    await bus.stop()

@pytest.mark.asyncio
async def test_stream_cancellation():
    bus = EventBus()
    await bus.start()
    agg = ResponseAggregator(bus)
    
    events = []
    async def track(e):
        events.append(e)
    bus.subscribe(EventType.STREAM_CANCELLED, track)
    
    stream_id = await agg.start_stream("test-model")
    await agg.cancel_stream(stream_id, "user_request")
    
    assert stream_id not in agg.active_streams
    await bus.drain()
    assert len(events) == 1
    await bus.stop()

@pytest.mark.asyncio
async def test_streaming_worker_lifecycle():
    bus = EventBus()
    await bus.start()
    agg = ResponseAggregator(bus)
    
    mock_ollama = MagicMock(spec=OllamaClient)
    async def mock_stream(prompt):
        yield "Part 1", False
        yield "Part 2", True
    mock_ollama.stream_generate = mock_stream
    mock_ollama.model = "test-model"
    
    worker = StreamingLlmWorker(bus, mock_ollama, agg)
    result = await worker.stream_reasoning("test prompt")
    
    assert result == "Part 1Part 2"
    await bus.drain()
    await bus.stop()

@pytest.mark.asyncio
async def test_streaming_worker_cancellation():
    bus = EventBus()
    await bus.start()
    agg = ResponseAggregator(bus)
    
    mock_ollama = MagicMock(spec=OllamaClient)
    async def mock_stream(prompt):
        await asyncio.sleep(10) # Simulate long generation
        yield "Never", True
    mock_ollama.stream_generate = mock_stream
    mock_ollama.model = "test-model"
    
    worker = StreamingLlmWorker(bus, mock_ollama, agg)
    task = asyncio.create_task(worker.stream_reasoning("test prompt"))
    await asyncio.sleep(0.1)
    task.cancel()
    
    with pytest.raises(asyncio.CancelledError):
        await task
        
    assert len(worker._active_tasks) == 0
    await bus.drain()
    await bus.stop()
