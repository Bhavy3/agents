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
    await asyncio.sleep(0.1)
    
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
    await asyncio.sleep(0.1)
    
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
