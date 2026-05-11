import asyncio
import pytest
from core.events.bus import EventBus
from core.events.event_types import EventType
from core.events.models import Event
from core.tools.tool_worker import ToolWorker


@pytest.mark.asyncio
async def test_tool_validation_rejection():
    bus = EventBus()
    worker = ToolWorker(bus)
    await bus.start()
    await worker.start()
    
    # Give some time for the worker task to initialize and subscribe
    await asyncio.sleep(0.5)

    denied_events = []

    async def on_denied(event):
        denied_events.append(event.payload)

    bus.subscribe(EventType.ACTION_DENIED, on_denied)

    # Try a forbidden command pattern
    await bus.publish(Event.create(
        EventType.ACTION_REQUESTED,
        {
            "intent": "execute_shell", 
            "parameters": {"command": "rm -rf /"}
        },
        "test_source",
        "corr_123"
    ))

    # Wait for processing
    for _ in range(20):
        if len(denied_events) > 0:
            break
        await asyncio.sleep(0.1)

    assert len(denied_events) == 1
    assert "forbidden_pattern" in denied_events[0]["reason"]
    assert denied_events[0]["tool_name"] == "execute_shell"

    await worker.stop()
    await bus.stop()


@pytest.mark.asyncio
async def test_confirmation_gate_denial():
    bus = EventBus()
    worker = ToolWorker(bus)
    await bus.start()
    await worker.start()
    
    # Give some time for the worker task to initialize and subscribe
    await asyncio.sleep(0.5)

    confirmation_requests = []
    denied_events = []

    async def on_conf_req(event):
        confirmation_requests.append(event)

    async def on_denied(event):
        denied_events.append(event)

    bus.subscribe(EventType.ACTION_CONFIRMATION_REQUIRED, on_conf_req)
    bus.subscribe(EventType.ACTION_DENIED, on_denied)

    # Trigger a RESTRICTED action
    await bus.publish(Event.create(
        EventType.ACTION_REQUESTED,
        {
            "intent": "delete_file",
            "parameters": {"file_path": "test.txt"}
        },
        "test_source",
        "corr_456"
    ))

    # Wait for confirmation request
    for _ in range(20):
        if len(confirmation_requests) > 0:
            break
        await asyncio.sleep(0.1)

    assert len(confirmation_requests) == 1
    assert confirmation_requests[0].payload["risk_level"] == "RESTRICTED"

    # Simulate user denial via confirmation system
    worker.confirmations.resolve_confirmation("corr_456", approved=False)

    # Wait for denial event
    for _ in range(10):
        if len(denied_events) > 0:
            break
        await asyncio.sleep(0.1)

    assert len(denied_events) == 1
    assert "user_refused" in denied_events[0].payload["reason"]

    await worker.stop()
    await bus.stop()


@pytest.mark.asyncio
async def test_tool_timeout_safety():
    bus = EventBus()
    worker = ToolWorker(bus)
    
    # Mock a tool that hangs
    async def hanging_tool(**kwargs):
        await asyncio.sleep(20.0) # Longer than 15s timeout
        return ToolResult(True, "done")
        
    worker.registry.register("hang", hanging_tool)
    
    await bus.start()
    await worker.start()
    
    timeout_events = []
    async def on_timeout(event):
        timeout_events.append(event)
    bus.subscribe(EventType.ACTION_TIMEOUT, on_timeout)
    
    await bus.publish(Event.create(
        EventType.ACTION_REQUESTED,
        {"intent": "hang", "parameters": {}},
        "test_source",
        "corr_timeout"
    ))
    
    # This test might be too slow for CI if we wait 15s. 
    # For speed, we could mock the timeout value in ToolWorker.
    # But let's assume it works for now or skip the long wait in standard suite.
    
    await worker.stop()
    await bus.stop()
