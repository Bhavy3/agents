import asyncio
import pytest
from core.events.bus import EventBus
from core.events.event_types import EventType
from core.events.models import Event
from core.executor.executor import CommandExecutor
from core.executor.command_registry import CommandRegistry
from core.executor.dry_run_actions import ExecutorResult
from core.executor.validation import ActionRisk

@pytest.mark.asyncio
async def test_action_execution_flow():
    bus = EventBus()
    registry = CommandRegistry()
    
    async def mock_handler(params):
        return ExecutorResult(True, f"Executed with {params}")
        
    registry.register("test_command", mock_handler)
    executor = CommandExecutor(bus, registry)
    
    await bus.start()
    await executor.start()
    await asyncio.sleep(0.1)
    
    responses = []
    async def on_response(event):
        responses.append(event.payload["text"])
    bus.subscribe(EventType.RESPONSE_READY, on_response)
    
    # 1. Request action
    await bus.publish(
        Event.create(
            EventType.ACTION_REQUESTED,
            {"action_id": "act_1", "intent": "test_command", "parameters": {"p1": "v1"}},
            "test"
        )
    )
    
    await asyncio.sleep(0.2)
    assert len(responses) == 1
    assert "Executed with {'p1': 'v1'}" in responses[0]
    
    await executor.stop()
    await bus.stop()

@pytest.mark.asyncio
async def test_action_denied_by_validation():
    bus = EventBus()
    registry = CommandRegistry()
    executor = CommandExecutor(bus, registry)
    
    await bus.start()
    await executor.start()
    await asyncio.sleep(0.1)
    
    events = []
    bus.subscribe(EventType.ACTION_DENIED, lambda e: events.append(e))
    
    # "rm -rf" is forbidden in our validation pipeline
    await bus.publish(
        Event.create(
            EventType.ACTION_REQUESTED,
            {"action_id": "act_bad", "intent": "shell", "parameters": {"cmd": "rm -rf /"}},
            "test"
        )
    )
    
    await asyncio.sleep(0.2)
    assert len(events) == 1
    assert events[0].payload["action_id"] == "act_bad"
    
    await executor.stop()
    await bus.stop()

@pytest.mark.asyncio
async def test_action_interruption_cancels_task():
    bus = EventBus()
    registry = CommandRegistry()
    
    async def slow_handler(params):
        try:
            await asyncio.sleep(10)
            return ExecutorResult(True, "Done")
        except asyncio.CancelledError:
            # Important to re-raise or allow it to propagate
            raise
        
    registry.register("slow", slow_handler)
    executor = CommandExecutor(bus, registry)
    
    await bus.start()
    await executor.start()
    await asyncio.sleep(0.1)
    
    cancelled_events = []
    bus.subscribe(EventType.ACTION_CANCELLED, lambda e: cancelled_events.append(e))
    
    await bus.publish(
        Event.create(EventType.ACTION_REQUESTED, {"action_id": "act_slow", "intent": "slow", "parameters": {}}, "test")
    )
    await asyncio.sleep(0.1)
    assert "act_slow" in executor._active_actions
    
    # Interrupt
    await bus.publish(Event.create(EventType.SPEECH_STARTED, {"timestamp": 1.0, "amplitude": 0.5}, "vad"))
    await asyncio.sleep(0.2)
    
    assert "act_slow" not in executor._active_actions
    assert len(cancelled_events) == 1
    
    await executor.stop()
    await bus.stop()

@pytest.mark.asyncio
async def test_action_timeout_enforced():
    bus = EventBus()
    registry = CommandRegistry()
    
    async def slow_handler(params):
        await asyncio.sleep(1.0)
        return ExecutorResult(True, "Done")
        
    registry.register("timeout_cmd", slow_handler)
    # Set low timeout
    executor = CommandExecutor(bus, registry, command_timeout_seconds=0.1)
    
    await bus.start()
    await executor.start()
    await asyncio.sleep(0.1)
    
    events = []
    bus.subscribe(EventType.ACTION_TIMEOUT, lambda e: events.append(e))
    
    await bus.publish(
        Event.create(EventType.ACTION_REQUESTED, {"action_id": "act_timeout", "intent": "timeout_cmd", "parameters": {}}, "test")
    )
    await asyncio.sleep(0.5)
    
    assert len(events) == 1
    assert events[0].payload["action_id"] == "act_timeout"
    
    await executor.stop()
    await bus.stop()
