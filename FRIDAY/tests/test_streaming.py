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
async def test_streaming_worker_uses_routed_model_and_reason_on_next_stream():
    """A route selection is visible on the next stream and reaches the fake client."""
    bus = EventBus()
    await bus.start()
    agg = ResponseAggregator(bus)
    started = []
    client_models = []

    async def track(event):
        started.append(event)

    bus.subscribe(EventType.STREAM_STARTED, track)

    class FakeClient:
        model = "configured-backend"

        def set_model(self, model, reason=""):
            self.model = model
            self.reason = reason

        async def stream_generate(self, prompt):
            client_models.append((self.model, self.reason))
            yield "routed", True

    client = FakeClient()
    worker = StreamingLlmWorker(bus, client, agg)
    worker.set_model("7b", "complex_query_needs_7b")

    assert await worker.stream_reasoning("test prompt") == "routed"
    await bus.drain()

    assert client_models == [("7b", "complex_query_needs_7b")]
    assert len(started) == 1
    assert started[0].payload["model"] == "7b"
    assert started[0].payload["reason"] == "complex_query_needs_7b"
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


@pytest.mark.asyncio
async def test_streaming_worker_timeout_emits_stream_timeout_event():
    bus = EventBus()
    await bus.start()
    agg = ResponseAggregator(bus)

    events = []
    async def track(e):
        events.append(e)
    bus.subscribe(EventType.STREAM_TIMEOUT, track)

    mock_ollama = MagicMock(spec=OllamaClient)
    async def mock_stream(prompt):
        await asyncio.sleep(1.0)
        yield "late", True
    mock_ollama.stream_generate = mock_stream
    mock_ollama.model = "test-model"
    mock_ollama.timeout_seconds = 0.1

    worker = StreamingLlmWorker(bus, mock_ollama, agg, timeout_seconds=0.1)
    result = await worker.stream_reasoning("test prompt")
    await bus.drain()

    assert result == ""
    assert sum(1 for e in events if e.event_type == EventType.STREAM_TIMEOUT) == 1
    assert len(worker._active_tasks) == 0
    await bus.stop()


@pytest.mark.asyncio
async def test_streaming_worker_timeout_cleans_up_active_task_once():
    bus = EventBus()
    await bus.start()
    agg = ResponseAggregator(bus)

    timeout_events = []
    async def track(e):
        timeout_events.append(e)
    bus.subscribe(EventType.STREAM_TIMEOUT, track)

    mock_ollama = MagicMock(spec=OllamaClient)
    async def mock_stream(prompt):
        await asyncio.sleep(0.5)
        yield "late", True
    mock_ollama.stream_generate = mock_stream
    mock_ollama.model = "test-model"

    worker = StreamingLlmWorker(bus, mock_ollama, agg, timeout_seconds=0.05)
    result = await worker.stream_reasoning("test prompt")
    await bus.drain()

    assert result == ""
    assert len(timeout_events) == 1
    assert len(worker._active_tasks) == 0
    await bus.stop()
