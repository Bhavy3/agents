import asyncio
import pytest
from core.events.bus import EventBus
from core.events.event_types import EventType
from core.events.models import Event, EventState
from core.exceptions import ValidationError
from core.executor.executor import CommandExecutor
from core.executor.command_registry import CommandRegistry
from core.executor.dry_run_actions import ExecutorResult

@pytest.mark.asyncio
async def test_invalid_event_payload_rejected():
    bus = EventBus(max_queue_size=10)
    await bus.start()
    
    # Missing required field 'text'
    invalid_event = Event.create(EventType.USER_TEXT_RECEIVED, payload={})
    
    # In EventBus, we drop malformed events silently but publish a MALFORMED_EVENT_DROPPED event
    dropped_events = []
    async def track_dropped(event):
        if event.event_type == EventType.MALFORMED_EVENT_DROPPED:
            dropped_events.append(event)
    
    bus.subscribe(EventType.MALFORMED_EVENT_DROPPED, track_dropped)
    
    # We need to bypass the _validate_event_boundary check which is called in publish
    # Actually publish calls it, so it should work.
    await bus.publish(invalid_event)
    
    # Wait a bit for the drop event to be processed
    for _ in range(10):
        if len(dropped_events) > 0:
            break
        await asyncio.sleep(0.01)
        
    assert len(dropped_events) == 1
    assert dropped_events[0].payload["reason"] == "contract_violation"
    await bus.stop()

@pytest.mark.asyncio
async def test_event_lifecycle_transitions():
    bus = EventBus(max_queue_size=10)
    await bus.start()
    
    event = Event.create(EventType.USER_TEXT_RECEIVED, payload={"text": "hello"})
    assert event.state == EventState.CREATED
    
    processed = asyncio.Event()
    async def handler(e):
        assert e.state == EventState.PROCESSING
        processed.set()
        
    bus.subscribe(EventType.USER_TEXT_RECEIVED, handler)
    await bus.publish(event)
    await processed.wait()
    await bus.drain()
    
    assert event.state == EventState.COMPLETED
    await bus.stop()

@pytest.mark.asyncio
async def test_executor_command_timeout():
    bus = EventBus(max_queue_size=10)
    registry = CommandRegistry()
    
    async def slow_handler(params):
        await asyncio.sleep(0.5)
        return ExecutorResult(success=True, message="done")
    
    registry.register("slow", slow_handler)
    executor = CommandExecutor(bus, registry, command_timeout_seconds=0.1)
    await bus.start()
    await executor.start()
    await asyncio.sleep(0.1)
    
    result_event = asyncio.Event()
    command_results = []
    async def track_result(e):
        command_results.append(e)
        result_event.set()
        
    bus.subscribe(EventType.ACTION_TIMEOUT, track_result)
    
    # Trigger command via event
    await bus.publish(Event.create(EventType.ACTION_REQUESTED, payload={
        "action_id": "act_timeout",
        "intent": "slow",
        "parameters": {}
    }))
    
    try:
        await asyncio.wait_for(result_event.wait(), timeout=1.0)
    except asyncio.TimeoutError:
        pytest.fail("Action timeout event not received")
        
    await bus.drain()
    await executor.stop()
    await bus.stop()
    
    assert len(command_results) == 1
    assert command_results[0].payload["action_id"] == "act_timeout"
