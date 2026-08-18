import asyncio
import time
import pytest
from core.events.bus import EventBus
from core.events.event_types import EventType
from core.events.models import Event
from core.cognition.cognitive_worker import CognitiveWorker
from core.cognition.attention_manager import AttentionPriority
from core.cognition.cognitive_state import TurnState

@pytest.mark.asyncio
async def test_speech_interruption_coordination():
    bus = EventBus()
    await bus.start()
    
    worker = CognitiveWorker(bus)
    await worker.start()
    await asyncio.sleep(0.1) # Wait for subscriptions
    
    # Simulate speech started via USER_SPEECH status="started"
    await bus.publish(Event.create(EventType.USER_SPEECH, {"status": "started", "amplitude": 0.5, "timestamp": time.time()}, "test"))
    await asyncio.sleep(0.1)
    
    # Verify state updates
    state = await worker.state_engine.get_state()
    assert state.active_speaker == "user"
    assert state.listening is True
    assert worker.attention.get_owner() == "user_speech"
    assert worker.attention.get_priority() == AttentionPriority.CRITICAL_INTERRUPTION
    
    await worker.stop()
    await bus.stop()

@pytest.mark.asyncio
async def test_turn_acquisition_coordination():
    bus = EventBus()
    await bus.start()
    
    worker = CognitiveWorker(bus)
    await worker.start()
    await asyncio.sleep(0.1)
    
    # Simulate assistant response started
    await bus.publish(Event.create(EventType.ASSISTANT_RESPONSE, {"status": "started", "turn_id": "turn_123"}, "test"))
    await asyncio.sleep(0.1)
    
    # Verify cognitive state engine turn state
    state = await worker.state_engine.get_state()
    assert state.active_turn_id == "turn_123"
    assert state.turn_state == TurnState.RESPONDING

    assert state.active_speaker == "assistant"
    assert state.speaking is True
    
    await worker.stop()
    await bus.stop()

@pytest.mark.asyncio
async def test_duplicate_turn_blocking():
    bus = EventBus()
    await bus.start()
    
    worker = CognitiveWorker(bus)
    await worker.start()
    await asyncio.sleep(0.1)
    
    # 1. Acquire turn 1
    await bus.publish(Event.create(EventType.ASSISTANT_RESPONSE, {"status": "started", "turn_id": "turn_1"}, "test"))
    await asyncio.sleep(0.1)
    state = await worker.state_engine.get_state()
    assert state.active_turn_id == "turn_1"
    
    # 2. Attempt turn 2 while turn 1 is active
    await bus.publish(Event.create(EventType.ASSISTANT_RESPONSE, {"status": "started", "turn_id": "turn_2"}, "test"))
    await asyncio.sleep(0.1)
    
    # Should still be turn 1
    state = await worker.state_engine.get_state()
    assert state.active_turn_id == "turn_1"
    
    await worker.stop()
    await bus.stop()
