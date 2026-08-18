import asyncio
import time
import uuid
from core.events.bus import EventBus
from core.events.event_types import EventType
from core.events.models import Event, EventPriority
from core.cognition.cognitive_worker import CognitiveWorker
from core.cognition.cognitive_state import TurnState

async def run_chaos_test():
    print("STARTING FRIDAY REALITY CHECK (CHAOS MODE)")
    bus = EventBus()
    await bus.start()
    
    worker = CognitiveWorker(bus)
    await worker.start()
    await asyncio.sleep(0.5) # Wait for initialization
    
    # 1. INTERRUPTION WAR TEST
    print("\n1. INTERRUPTION WAR TEST")
    # Simulate user speaking while assistant is thinking/responding
    await bus.publish(Event.create(EventType.ASSISTANT_RESPONSE, {"status": "started", "turn_id": "turn_A"}, "test"))
    await asyncio.sleep(0.1)
    state_val = await worker.state_engine.get_state()
    print(f"Assistant state: {state_val.turn_state}")
    
    print("Simulating rapid interruption...")
    await bus.publish(Event.create(EventType.SPEECH_STARTED, {"amplitude": 0.8, "timestamp": time.time()}, "vad"))
    await asyncio.sleep(0.1)
    
    state = await worker.state_engine.get_state()
    print(f"Cognitive state after interrupt: active_speaker={state.active_speaker}, turn_id={state.active_turn_id}")
    if state.active_speaker == "user":
        print("SUCCESS: Clean cancellation: Assistant turn revoked.")
    else:
        print("FAILURE: Assistant still owns speaker state!")

    # 2. EVENT BUS CHAOS TEST (Flooding)
    print("\n2. EVENT BUS CHAOS TEST")
    print("Flooding with malformed and duplicate events...")
    for _ in range(50):
        # Malformed (missing fields)
        await bus.publish(Event.create(EventType.SPEECH_STARTED, {"junk": "data"}, "chaos"))
        # Duplicate response started
        await bus.publish(Event.create(EventType.ASSISTANT_RESPONSE, {"status": "started", "turn_id": "turn_B"}, "chaos"))
    
    await asyncio.sleep(0.5)
    print("Queue processed. Checking system stability...")
    state = await worker.state_engine.get_state()
    print(f"System alive? {worker.health.state}")
    
    # 3. TURN OWNERSHIP TEST (Strict lock)
    print("\n3. TURN OWNERSHIP TEST")
    # First, ensure idle
    await bus.publish(Event.create(EventType.ASSISTANT_RESPONSE, {"status": "completed", "turn_id": "turn_B", "text": "done"}, "test"))
    await asyncio.sleep(0.1)
    
    await bus.publish(Event.create(EventType.ASSISTANT_RESPONSE, {"status": "started", "turn_id": "turn_C"}, "test"))
    await asyncio.sleep(0.1)
    state_val = await worker.state_engine.get_state()
    print(f"Current Turn: {state_val.active_turn_id}")
    
    print("Attempting to hijack turn with turn_D...")
    await bus.publish(Event.create(EventType.ASSISTANT_RESPONSE, {"status": "started", "turn_id": "turn_D"}, "test"))
    await asyncio.sleep(0.1)
    
    state_val = await worker.state_engine.get_state()
    final_turn = state_val.active_turn_id
    print(f"Final Turn: {final_turn}")
    if final_turn == "turn_C":
        print("SUCCESS: Duplicate turn blocked by state engine.")
    else:
        print(f"FAILURE: Turn state was {final_turn}")

    # 4. TTS GHOST TEST (Rapid toggle)
    print("\n4. TTS GHOST TEST")
    print("Rapidly toggling speech...")
    for i in range(5):
        await bus.publish(Event.create(EventType.SPEECH_STARTED, {"amplitude": 0.9, "timestamp": time.time()}, "vad"))
        await asyncio.sleep(0.05)
        await bus.publish(Event.create(EventType.SPEECH_ENDED, {"duration": 0.1, "timestamp": time.time()}, "vad"))
    
    await asyncio.sleep(0.2)
    state = await worker.state_engine.get_state()
    print(f"Final speaker state: {state.active_speaker}")

    print("\nCHAOS TEST COMPLETE")
    await worker.stop()
    await asyncio.sleep(0.1) # Let worker stop
    await bus.stop()

if __name__ == "__main__":
    asyncio.run(run_chaos_test())
