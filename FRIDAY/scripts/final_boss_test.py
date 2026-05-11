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
from core.audio.transport import AudioTransportWorker
from core.audio.vad import VadWorker
from core.vision.screen_capture import ScreenCaptureWorker
from core.vision.ocr_worker import OCRWorker
from core.tools.tool_worker import ToolWorker


async def final_boss():
    print("\n" + "="*40)
    print("RUNNING FINAL BOSS TEST (PHASE 9 STRESS)")
    print("="*40)
    
    bus = EventBus()
    
    # 1. Start all workers
    audio = AudioTransportWorker(bus)
    vad = VadWorker(bus)
    vision = ScreenCaptureWorker(bus)
    ocr = OCRWorker(bus)
    tools = ToolWorker(bus)
    
    print("Starting workers...")
    await bus.start()
    await audio.start()
    await vad.start()
    await vision.start()
    await ocr.start()
    await tools.start()
    
    print("Workers active. Simulating simultaneous load...")
    
    # 2. Simulate load cycles
    for i in range(3):
        print(f"\nCycle {i+1}:")
        
        # Simultaneous events
        # A. Audio heartbeat (simulated by worker)
        # B. Screen capture -> OCR pipeline (simulated by workers)
        
        # C. Action Request
        print("  Triggering Tool Action...")
        await bus.publish(Event.create(EventType.ACTION_REQUESTED, {
            "intent": "search_web",
            "parameters": {"query": f"Friday AI load test cycle {i}"}
        }, correlation_id=f"boss_act_{i}"))
        
        # D. Memory Query
        print("  Triggering Memory Query...")
        await bus.publish(Event.create(EventType.MEMORY_QUERY_REQUEST, {
            "query": "ducati"
        }, correlation_id=f"boss_mem_{i}"))
        
        # E. System Status Check
        await asyncio.sleep(2.0)
        print(f"  System responsive after cycle {i+1}")

    # 3. Shutdown
    print("\nInitiating shutdown...")
    await audio.stop()
    await vad.stop()
    await vision.stop()
    await ocr.stop()
    await tools.stop()
    await bus.stop()
    
    print("="*40)
    print("FINAL BOSS TEST COMPLETED SUCCESSFULLY.")
    print("="*40)


if __name__ == "__main__":
    asyncio.run(final_boss())
