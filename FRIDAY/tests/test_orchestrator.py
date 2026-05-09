import asyncio
import pytest
from unittest.mock import AsyncMock, patch

from core.orchestrator.conversation import OrchestratorWorker
from core.events.bus import EventBus
from core.events.event_types import EventType
from core.events.models import Event


@pytest.mark.asyncio
async def test_orchestrator_turn_ownership():
    bus = EventBus()
    await bus.start()
    
    mock_intent_router = AsyncMock()
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
    
    mock_intent_router.handle_user_text.assert_called_once()
    assert orchestrator.active_speaker == "assistant"
    
    await orchestrator.stop()
    await task
    await bus.stop()


@pytest.mark.asyncio
async def test_orchestrator_interruption():
    bus = EventBus()
    await bus.start()
    
    mock_intent_router = AsyncMock()
    # Make routing slow so it can be interrupted
    async def slow_route(*args, **kwargs):
        await asyncio.sleep(1.0)
    mock_intent_router.handle_user_text.side_effect = slow_route
    
    mock_streaming_worker = AsyncMock()
    
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
    
    mock_intent_router = AsyncMock()
    # Make routing VERY slow to trigger timeout
    async def slow_route(*args, **kwargs):
        await asyncio.sleep(5.0)
    mock_intent_router.handle_user_text.side_effect = slow_route
    
    mock_streaming_worker = AsyncMock()
    
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
