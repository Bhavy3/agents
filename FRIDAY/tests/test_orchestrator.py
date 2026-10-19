import asyncio
import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch, MagicMock

from core.orchestrator.conversation import OrchestratorWorker
from core.events.bus import EventBus
from core.events.event_types import EventType
from core.events.models import Event
from core.llm.stream_aggregator import ResponseAggregator
from core.llm.streaming_worker import StreamingLlmWorker

@pytest.fixture(autouse=True)
def mock_thinking_delay():
    with patch("core.personality.presence.PresenceManager.simulate_thinking_delay", new_callable=AsyncMock) as mock:
        yield mock


async def _wait_until(predicate):
    for _ in range(100):
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition was not satisfied before timeout")


@pytest.mark.asyncio
async def test_normal_orchestrator_shutdown_does_not_log_timeout_cancellation(caplog):
    bus = EventBus()
    await bus.start()
    orchestrator = OrchestratorWorker(bus, None, AsyncMock())
    task = asyncio.create_task(orchestrator.work())
    await asyncio.sleep(0)

    with caplog.at_level("WARNING", logger="workers.orchestrator"):
        task.cancel()
        await task

    assert not any(
        record.getMessage() == "workflow_timeout_monitor_cancelled"
        for record in caplog.records
    )
    await bus.stop()


@pytest.mark.asyncio
async def test_text_prompts_arriving_during_a_turn_are_queued_not_dropped():
    from core.router.rules import Intent, IntentName

    bus = EventBus()
    await bus.start()
    router = AsyncMock()
    router.route.side_effect = lambda text, **_: Intent(
        IntentName.CHAT,
        1.0,
        {"response_text": f"Reply to {text}"},
        source="test",
    )
    class StreamingWorkerStub:
        def cancel_all(self):
            return None

    orchestrator = OrchestratorWorker(bus, router, StreamingWorkerStub())
    completed = []

    async def capture(event):
        if event.event_type == EventType.RESPONSE_READY:
            completed.append(event)

    bus.subscribe(EventType.RESPONSE_READY, capture)
    task = asyncio.create_task(orchestrator.run())
    await asyncio.sleep(0)
    prompts = [(f"text-turn-{index}", f"prompt {index}") for index in range(3)]

    for correlation_id, text in prompts:
        await bus.publish(Event.create(
            EventType.USER_TEXT_RECEIVED,
            {"text": text},
            "test_cli",
            correlation_id,
        ))
        await asyncio.sleep(0.03)

    for _ in range(300):
        if len(completed) == 3:
            break
        await asyncio.sleep(0.01)
    assert len(completed) == 3, [event.correlation_id for event in completed]
    assert [event.correlation_id for event in completed] == [item[0] for item in prompts]
    assert [event.payload["text"] for event in completed] == [
        f"Reply to {text}" for _, text in prompts
    ]

    await orchestrator.stop()
    await task
    await bus.stop()


@pytest.mark.asyncio
async def test_queued_text_resumes_after_workflow_terminal_event():
    bus = EventBus()
    await bus.start()

    class StreamingWorkerStub:
        def cancel_all(self):
            return None

    orchestrator = OrchestratorWorker(bus, None, StreamingWorkerStub())
    starts = []
    responses = []

    async def capture_start(event):
        starts.append(event)

    async def capture_response(event):
        if event.event_type == EventType.RESPONSE_READY:
            responses.append(event)

    bus.subscribe(EventType.CONVERSATION_TURN_STARTED, capture_start)
    bus.subscribe(EventType.RESPONSE_READY, capture_response)
    task = asyncio.create_task(orchestrator.run())
    await asyncio.sleep(0)

    orchestrator.active_turn_id = "active-workflow-turn"
    orchestrator.active_speaker = "assistant"
    orchestrator._turn_ids_by_correlation_id["workflow-origin"] = "active-workflow-turn"
    orchestrator._pending_workflow_correlations.add("workflow-origin")
    await bus.publish(Event.create(
        EventType.USER_TEXT_RECEIVED,
        {"text": "queued follow-up"},
        "test_cli",
        "queued-follow-up",
    ))
    await asyncio.sleep(0.05)
    assert not any(event.correlation_id == "queued-follow-up" for event in starts)

    await bus.publish(Event.create(
        EventType.ACTION_GRAPH_COMPLETED,
        {"graph_id": "active-workflow", "success": True},
        "workflow_test",
        "workflow-origin",
    ))
    await _wait_until(lambda: any(event.correlation_id == "queued-follow-up" for event in responses))

    assert [event.correlation_id for event in starts] == ["queued-follow-up"]
    await orchestrator.stop()
    await task
    await bus.stop()


@pytest.mark.asyncio
async def test_orchestrator_turn_ownership():
    from core.router.rules import Intent, IntentName
    
    bus = EventBus()
    await bus.start()
    await bus.start()
    
    mock_intent_router = AsyncMock()
    mock_intent_router.route.return_value = Intent(IntentName.CHAT, 0.99, {})
    mock_streaming_worker = AsyncMock()
    
    orchestrator = OrchestratorWorker(bus, mock_intent_router, mock_streaming_worker)
    
    events = []
    async def track(e):
        events.append(e)
        
    bus.subscribe(EventType.CONVERSATION_TURN_STARTED, track)
    bus.subscribe(EventType.USER_MESSAGE_RECEIVED, track)
    
    task = asyncio.create_task(orchestrator.run())
    await asyncio.sleep(0.1)
    
    await bus.publish(Event.create(EventType.STT_FINAL_TRANSCRIPT, {"segment_id": "seg_1", "text": "hello", "duration": 1.0, "confidence": 0.99}, "stt"))
    await _wait_until(lambda: mock_intent_router.route.await_count == 1)
    
    assert len(events) == 2
    assert events[0].event_type == EventType.CONVERSATION_TURN_STARTED
    assert events[1].event_type == EventType.USER_MESSAGE_RECEIVED
    assert events[1].payload["text"] == "hello"
    
    mock_intent_router.route.assert_called_once()
    assert orchestrator.active_speaker == "assistant"
    
    await orchestrator.stop()
    await task
    await bus.stop()


@pytest.mark.asyncio
async def test_orchestrator_falls_back_to_chat_when_router_missing():
    bus = EventBus()
    await bus.start()

    mock_streaming_worker = AsyncMock()
    orchestrator = OrchestratorWorker(bus, None, mock_streaming_worker)

    responses = []
    async def track(e):
        if e.event_type == EventType.RESPONSE_READY:
            responses.append(e)

    bus.subscribe(EventType.RESPONSE_READY, track)

    task = asyncio.create_task(orchestrator.run())
    await asyncio.sleep(0.1)

    await bus.publish(Event.create(EventType.STT_FINAL_TRANSCRIPT, {"segment_id": "seg_1", "text": "hello", "duration": 1.0, "confidence": 0.99}, "stt"))
    await _wait_until(lambda: bool(responses))

    assert len(responses) == 1
    assert responses[0].payload["text"] == "I'm unable to reach the conversation router right now. Please try again."
    assert "hello" not in responses[0].payload["text"].lower()
    assert orchestrator.active_speaker is None
    assert orchestrator._routing_task is None

    await orchestrator.stop()
    await task
    await bus.stop()


@pytest.mark.asyncio
async def test_orchestrator_falls_back_to_chat_when_route_returns_none():
    bus = EventBus()
    await bus.start()

    mock_router = AsyncMock()
    mock_router.route.return_value = None
    mock_streaming_worker = AsyncMock()
    orchestrator = OrchestratorWorker(bus, mock_router, mock_streaming_worker)

    responses = []
    async def track_response(e):
        responses.append(e)
    bus.subscribe(EventType.RESPONSE_READY, track_response)

    task = asyncio.create_task(orchestrator.run())
    await asyncio.sleep(0.1)

    await bus.publish(Event.create(EventType.STT_FINAL_TRANSCRIPT, {"segment_id": "seg_1", "text": "hello", "duration": 1.0, "confidence": 0.99}, "stt"))
    await _wait_until(lambda: bool(responses))

    assert len(responses) == 1
    assert responses[0].payload["text"] == "I'm unable to reach the conversation router right now. Please try again."
    assert "hello" not in responses[0].payload["text"].lower()
    assert orchestrator.active_speaker is None
    assert orchestrator._routing_task is None

    await orchestrator.stop()
    await task
    await bus.stop()


@pytest.mark.asyncio
async def test_orchestrator_falls_back_when_router_raises(caplog):
    bus = EventBus()
    await bus.start()

    mock_router = AsyncMock()
    mock_router.route.side_effect = RuntimeError("router unavailable")
    mock_streaming_worker = AsyncMock()
    orchestrator = OrchestratorWorker(bus, mock_router, mock_streaming_worker)

    responses = []
    async def track_response(e):
        responses.append(e)
    bus.subscribe(EventType.RESPONSE_READY, track_response)

    task = asyncio.create_task(orchestrator.run())
    await asyncio.sleep(0.1)

    await bus.publish(Event.create(EventType.STT_FINAL_TRANSCRIPT, {"segment_id": "seg_1", "text": "private input", "duration": 1.0, "confidence": 0.99}, "stt"))
    await _wait_until(lambda: bool(responses))

    assert len(responses) == 1
    assert responses[0].payload["text"] == "I'm unable to reach the conversation router right now. Please try again."
    assert "private input" not in responses[0].payload["text"].lower()
    assert orchestrator.active_turn_id is None
    assert orchestrator.active_speaker is None
    assert orchestrator._routing_task is None
    assert any(
        record.message == "intent_router_route_failed" and record.exc_info is not None
        for record in caplog.records
    )

    await orchestrator.stop()
    await task
    await bus.stop()


@pytest.mark.asyncio
async def test_orchestrator_normal_chat_response_still_works():
    bus = EventBus()
    await bus.start()

    mock_router = AsyncMock()
    mock_router.route.return_value = AsyncMock(name="Intent")
    from core.router.rules import Intent, IntentName
    mock_router.route.return_value = Intent(IntentName.CHAT, 0.99, {"response_text": "Normal chat reply"})
    mock_streaming_worker = AsyncMock()
    orchestrator = OrchestratorWorker(bus, mock_router, mock_streaming_worker)

    responses = []
    async def track_response(e):
        responses.append(e)
    bus.subscribe(EventType.RESPONSE_READY, track_response)

    task = asyncio.create_task(orchestrator.run())
    await asyncio.sleep(0.1)

    await bus.publish(Event.create(EventType.STT_FINAL_TRANSCRIPT, {"segment_id": "seg_1", "text": "hello", "duration": 1.0, "confidence": 0.99}, "stt"))
    await _wait_until(lambda: bool(responses))

    assert len(responses) == 1
    assert responses[0].payload["text"] == "Normal chat reply"
    assert orchestrator.active_speaker is None
    assert orchestrator._routing_task is None

    await orchestrator.stop()
    await task
    await bus.stop()


@pytest.mark.asyncio
async def test_orchestrator_applies_route_to_next_stream():
    """The orchestrator's tuple decision controls the shared streaming worker."""
    bus = EventBus()
    await bus.start()
    aggregator = ResponseAggregator(bus)
    observed = []

    class FakeClient:
        model = "configured-backend"

        def set_model(self, model, reason=""):
            self.model = model
            self.reason = reason

        async def stream_generate(self, prompt):
            observed.append((self.model, self.reason))
            yield "ok", True

    streaming_worker = StreamingLlmWorker(bus, FakeClient(), aggregator)
    orchestrator = OrchestratorWorker(bus, None, streaming_worker)
    orchestrator.adaptive_router = SimpleNamespace(
        route=AsyncMock(return_value=("7b", "complex_query_needs_7b"))
    )
    orchestrator._route_and_execute = AsyncMock()

    try:
        await orchestrator._initiate_turn("analyze the trends", "correlation")
        if orchestrator._routing_task is not None:
            await orchestrator._routing_task

        assert await streaming_worker.stream_reasoning("prompt", "correlation") == "ok"
        assert observed == [("7b", "complex_query_needs_7b")]
        assert streaming_worker.selected_model == "7b"
        assert streaming_worker.selection_reason == "complex_query_needs_7b"
    finally:
        await bus.stop()


@pytest.mark.asyncio
async def test_orchestrator_interruption():
    bus = EventBus()
    await bus.start()
    await bus.start()
    
    mock_intent_router = AsyncMock()
    # Make routing slow so it can be interrupted
    async def slow_route(*args, **kwargs):
        await asyncio.sleep(1.0)
    mock_intent_router.route.side_effect = slow_route
    
    mock_streaming_worker = AsyncMock()
    mock_streaming_worker.cancel_all = MagicMock()
    
    orchestrator = OrchestratorWorker(bus, mock_intent_router, mock_streaming_worker)
    
    events = []
    async def track(e):
        events.append(e)
        
    bus.subscribe(EventType.CONVERSATION_INTERRUPTED, track)
    
    task = asyncio.create_task(orchestrator.run())
    await asyncio.sleep(0.1)
    
    # 1. User says something
    await bus.publish(Event.create(EventType.STT_FINAL_TRANSCRIPT, {"segment_id": "seg_1", "text": "hello", "duration": 1.0, "confidence": 0.99}, "stt"))
    await _wait_until(lambda: mock_intent_router.route.await_count == 1)
    
    # Assert assistant is thinking/routing
    assert orchestrator.active_speaker == "assistant"
    assert orchestrator._routing_task is not None
    assert not orchestrator._routing_task.done()
    
    # 2. User interrupts by starting to speak
    await bus.publish(Event.create(EventType.SPEECH_STARTED, {"timestamp": 1.0, "amplitude": 0.5}, "vad"))
    await asyncio.sleep(0.1)
    
    # Assert assistant was interrupted
    assert orchestrator.active_speaker == "user"
    assert len(events) == 1
    assert events[0].event_type == EventType.CONVERSATION_INTERRUPTED
    
    mock_streaming_worker.cancel_all.assert_called_once()
    assert orchestrator._routing_task is None
    
    await orchestrator.stop()
    await task
    await bus.stop()


@pytest.mark.asyncio
async def test_orchestrator_timeout_recovery():
    bus = EventBus()
    await bus.start()
    await bus.start()
    
    mock_intent_router = AsyncMock()
    # Make routing VERY slow to trigger timeout
    async def slow_route(*args, **kwargs):
        await asyncio.sleep(5.0)
    mock_intent_router.route.side_effect = slow_route
    
    mock_streaming_worker = AsyncMock()
    mock_streaming_worker.cancel_all = MagicMock()
    
    # Set response timeout to 0.5s for fast test
    orchestrator = OrchestratorWorker(bus, mock_intent_router, mock_streaming_worker, response_timeout_seconds=0.5)
    
    events = []
    async def track(e):
        events.append(e)
        
    bus.subscribe(EventType.CONVERSATION_TIMEOUT, track)
    
    task = asyncio.create_task(orchestrator.run())
    await asyncio.sleep(0.1)
    
    await bus.publish(Event.create(EventType.STT_FINAL_TRANSCRIPT, {"segment_id": "seg_1", "text": "hello", "duration": 1.0, "confidence": 0.99}, "stt"))
    
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, MagicMock

from core.orchestrator.conversation import OrchestratorWorker
from core.events.bus import EventBus
from core.events.event_types import EventType
from core.events.models import Event

@pytest.fixture(autouse=True)
def mock_thinking_delay():
    with patch("core.personality.presence.PresenceManager.simulate_thinking_delay", new_callable=AsyncMock) as mock:
        yield mock


@pytest.mark.asyncio
async def test_orchestrator_turn_ownership():
    from core.router.rules import Intent, IntentName
    
    bus = EventBus()
    await bus.start()
    await bus.start()
    
    mock_intent_router = AsyncMock()
    mock_intent_router.route.return_value = Intent(IntentName.CHAT, 0.99, {})
    mock_streaming_worker = AsyncMock()
    
    orchestrator = OrchestratorWorker(bus, mock_intent_router, mock_streaming_worker)
    
    events = []
    async def track(e):
        events.append(e)
        
    bus.subscribe(EventType.CONVERSATION_TURN_STARTED, track)
    bus.subscribe(EventType.USER_MESSAGE_RECEIVED, track)
    
    task = asyncio.create_task(orchestrator.run())
    await asyncio.sleep(0.1)
    
    await bus.publish(Event.create(EventType.STT_FINAL_TRANSCRIPT, {"segment_id": "seg_1", "text": "hello", "duration": 1.0, "confidence": 0.99}, "stt"))
    await _wait_until(lambda: mock_intent_router.route.await_count == 1)
    
    assert len(events) == 2
    assert events[0].event_type == EventType.CONVERSATION_TURN_STARTED
    assert events[1].event_type == EventType.USER_MESSAGE_RECEIVED
    assert events[1].payload["text"] == "hello"
    
    mock_intent_router.route.assert_called_once()
    assert orchestrator.active_speaker is None
    
    await orchestrator.stop()
    await task
    await bus.stop()


@pytest.mark.asyncio
async def test_orchestrator_interruption():
    bus = EventBus()
    await bus.start()
    await bus.start()
    
    mock_intent_router = AsyncMock()
    # Make routing slow so it can be interrupted
    async def slow_route(*args, **kwargs):
        await asyncio.sleep(1.0)
    mock_intent_router.route.side_effect = slow_route
    
    mock_streaming_worker = AsyncMock()
    mock_streaming_worker.cancel_all = MagicMock()
    
    orchestrator = OrchestratorWorker(bus, mock_intent_router, mock_streaming_worker)
    
    events = []
    async def track(e):
        events.append(e)
        
    bus.subscribe(EventType.CONVERSATION_INTERRUPTED, track)
    
    task = asyncio.create_task(orchestrator.run())
    await asyncio.sleep(0.1)
    
    # 1. User says something
    await bus.publish(Event.create(EventType.STT_FINAL_TRANSCRIPT, {"segment_id": "seg_1", "text": "hello", "duration": 1.0, "confidence": 0.99}, "stt"))
    await asyncio.sleep(0.1)
    
    # Assert assistant is thinking/routing
    assert orchestrator.active_speaker == "assistant"
    assert orchestrator._routing_task is not None
    assert not orchestrator._routing_task.done()
    
    # 2. User interrupts by starting to speak
    await bus.publish(Event.create(EventType.SPEECH_STARTED, {"timestamp": 1.0, "amplitude": 0.5}, "vad"))
    await asyncio.sleep(0.1)
    
    # Assert assistant was interrupted
    assert orchestrator.active_speaker == "user"
    assert len(events) == 1
    assert events[0].event_type == EventType.CONVERSATION_INTERRUPTED
    
    mock_streaming_worker.cancel_all.assert_called_once()
    assert orchestrator._routing_task is None
    
    await orchestrator.stop()
    await task
    await bus.stop()


@pytest.mark.asyncio
async def test_orchestrator_timeout_recovery():
    bus = EventBus()
    await bus.start()
    await bus.start()
    
    mock_intent_router = AsyncMock()
    # Make routing VERY slow to trigger timeout
    async def slow_route(*args, **kwargs):
        await asyncio.sleep(5.0)
    mock_intent_router.route.side_effect = slow_route
    
    mock_streaming_worker = AsyncMock()
    mock_streaming_worker.cancel_all = MagicMock()
    
    # Set response timeout to 0.5s for fast test
    orchestrator = OrchestratorWorker(bus, mock_intent_router, mock_streaming_worker, response_timeout_seconds=0.5)
    
    events = []
    async def track(e):
        events.append(e)
        
    bus.subscribe(EventType.CONVERSATION_TIMEOUT, track)
    
    task = asyncio.create_task(orchestrator.run())
    await asyncio.sleep(0.1)
    
    await bus.publish(Event.create(EventType.STT_FINAL_TRANSCRIPT, {"segment_id": "seg_1", "text": "hello", "duration": 1.0, "confidence": 0.99}, "stt"))
    
    # Wait for work() loop to trigger timeout (sleep 1.5s because work() loop sleeps 1.0s)
    await asyncio.sleep(1.5)
    
    assert len(events) == 1
    assert events[0].payload["timeout_type"] == "routing_timeout"
    assert orchestrator.active_speaker is None
    
    await orchestrator.stop()
    await task
    await bus.stop()


@pytest.mark.asyncio
async def test_orchestrator_lock_regression():
    from core.orchestrator.conversation import OrchestratorWorker
    from core.events.bus import EventBus
    from core.events.event_types import EventType
    from core.events.models import Event
    from unittest.mock import AsyncMock, MagicMock
    import asyncio

    bus = EventBus()
    await bus.start()
    orchestrator = OrchestratorWorker(bus, AsyncMock(), MagicMock())
    
    # We want to simulate concurrent execution of two methods that mutate active_speaker
    event1 = Event.create(EventType.SPEECH_STARTED, {}, 'test')
    event2 = Event.create(EventType.STREAM_COMPLETED, {'full_text': 'hello'}, 'test')
    
    # Set initial state
    orchestrator.active_speaker = 'assistant'
    orchestrator.active_turn_id = 'turn1'
    orchestrator._chat_confirmed = True
    
    # Run concurrently
    await asyncio.gather(
        orchestrator._handle_speech_started(event1),
        orchestrator._handle_stream_completed(event2)
    )
    
    # Since SPEECH_STARTED sets active_speaker to 'user' and STREAM_COMPLETED sets it to None (if it was 'assistant'):
    # If stream_completed runs first: active_speaker becomes None. Then speech_started runs, sets it to 'user'.
    # If speech_started runs first: active_speaker becomes 'user'. Then stream_completed runs, ignores it.
    # Final state must always be 'user'.
    assert orchestrator.active_speaker == 'user'
