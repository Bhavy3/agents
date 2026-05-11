import asyncio
import os
import sys
from pathlib import Path

# Add project root to sys.path
root = Path(__file__).parent.parent
sys.path.insert(0, str(root))

from core.events.bus import EventBus
from core.events.event_types import EventType
from core.events.models import Event
from core.tools.tool_worker import ToolWorker


async def test_event_bus_flood():
    print("Testing Event Bus Flood...")
    bus = EventBus(max_queue_size=2000)
    count = 0

    async def handler(_):
        nonlocal count
        count += 1

    bus.subscribe(EventType.HEALTHCHECK, handler)
    await bus.start()
    for _ in range(1000):
        await bus.publish(Event.create(EventType.HEALTHCHECK, {}))
    await bus.drain()
    await bus.stop()
    print(f"  Received {count}/1000 events.")
    assert count == 1000


async def test_dangerous_command_blocking():
    print("Testing Dangerous Command Blocking...")
    bus = EventBus()
    worker = ToolWorker(bus)
    await bus.start()
    await worker.start()
    await asyncio.sleep(0.5)

    denied_events = []

    async def on_denied(e):
        denied_events.append(e)

    bus.subscribe(EventType.ACTION_DENIED, on_denied)

    await bus.publish(Event.create(EventType.ACTION_REQUESTED, {
        "intent": "delete_files",
        "parameters": {"path": "C:\\Windows\\System32"}
    }, correlation_id="corr_danger"))

    # Wait for processing
    for _ in range(20):
        if len(denied_events) > 0:
            break
        await asyncio.sleep(0.1)

    await worker.stop()
    await bus.stop()

    assert len(denied_events) >= 1
    print(f"  Denied action successfully: {denied_events[0].payload['reason']}")


async def test_safe_command():
    print("Testing Safe Command (Notepad)...")
    bus = EventBus()
    worker = ToolWorker(bus)
    await bus.start()
    await worker.start()
    await asyncio.sleep(0.5)

    started_events = []

    async def on_started(e):
        started_events.append(e)

    bus.subscribe(EventType.ACTION_STARTED, on_started)

    # Note: launch_app expects 'command' parameter
    await bus.publish(Event.create(EventType.ACTION_REQUESTED, {
        "intent": "launch_app",
        "parameters": {"command": "notepad.exe"}
    }, correlation_id="corr_safe"))

    # Wait for processing
    for _ in range(20):
        if len(started_events) > 0:
            break
        await asyncio.sleep(0.1)

    await worker.stop()
    await bus.stop()

    assert len(started_events) >= 1
    print("  Safe command started successfully.")


async def test_memory_persistence():
    print("Testing Memory Persistence...")
    from core.memory.memory_store import MemoryStore
    from core.memory.memory_models import MemoryRecord, MemoryType
    import time
    db_path = "test_verify_memory.db"
    if os.path.exists(db_path):
        os.remove(db_path)
    
    store = MemoryStore(db_path)
    
    record = MemoryRecord(
        id="test_1",
        type=MemoryType.PREFERENCE,
        content="my favorite bike is ducati",
        created_at=time.time(),
        updated_at=time.time(),
        source="verify_script",
        confidence=1.0,
        explicit_user_approved=True,
        metadata={}
    )
    await store.save(record)
    
    # Simulate restart
    store2 = MemoryStore(db_path)
    results = await store2.search_by_text("bike")
    
    assert any("ducati" in r.content for r in results)
    print("  Memory persistence verified.")
    try:
        if os.path.exists(db_path):
            os.remove(db_path)
    except Exception:
        pass


async def test_vision_sanity():
    print("Testing Vision Workers Sanity...")
    bus = EventBus()
    from core.vision.screen_capture import ScreenCaptureWorker
    from core.vision.ocr_worker import OCRWorker
    
    cap = ScreenCaptureWorker(bus)
    ocr = OCRWorker(bus)
    
    await bus.start()
    await cap.start()
    await ocr.start()
    
    await asyncio.sleep(1.0) # Let them initialize
    
    await cap.stop()
    await ocr.stop()
    await bus.stop()
    print("  Vision workers initialized and stopped successfully.")


async def main():
    try:
        await test_event_bus_flood()
        await test_memory_persistence()
        await test_vision_sanity()
        await test_dangerous_command_blocking()
        await test_safe_command()
        print("\nALL RUNTIME VERIFICATIONS PASSED.")
    except Exception as e:
        print(f"\nVERIFICATION FAILED: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
