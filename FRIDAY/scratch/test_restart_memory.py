import asyncio
import sys
import os

# Add FRIDAY dir to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.app import FridayApp
from core.events.event_types import EventType
from core.events.models import Event
from unittest.mock import AsyncMock

async def main():
    app = FridayApp()
    
    # MOCK OLLAMA TO AVOID CONNECTION ERRORS
    app.ollama_client.health_check = AsyncMock(return_value=True)
    class MockMetrics:
        success = True
    
    async def mock_generate(prompt, **kwargs):
        # We look for the memory context in the prompt
        if "NIGHTHAWK" in prompt:
            return '{"intent": "chat"}', MockMetrics()
        return '{"intent": "chat"}', MockMetrics()
    app.ollama_client.generate = AsyncMock(side_effect=mock_generate)
    
    # Also mock stream_generate for chat fallback
    async def mock_stream(prompt, **kwargs):
        if "NIGHTHAWK" in prompt:
            yield "Hello NIGHTHAWK! I see your code name in my memory."
        else:
            yield "I don't know your code name."
    app.ollama_client.stream_generate = mock_stream
    
    async def on_response(e: Event):
        print(f"\n[FRIDAY RESPONSE]: {e.payload.get('text', '')}")
        
    async def on_memory(e: Event):
        print(f"\n[MEMORY EVENT]: {e.payload.get('context', '')[:100]}...")

    await app.event_bus.start()
    app.event_bus.subscribe(EventType.RESPONSE_READY, on_response)
    app.event_bus.subscribe(EventType.MEMORY_CONTEXT_READY, on_memory)
    
    # Start the app (starts supervisor and workers)
    app_task = asyncio.create_task(app.start())
    
    print("Waiting 3 seconds for MemoryWorker to initialize and publish MEMORY_CONTEXT_READY...")
    await asyncio.sleep(3)
    
    print("\n--- SENDING QUESTION TO FRIDAY ---")
    await app.event_bus.publish(Event.create(
        EventType.USER_TEXT_RECEIVED, 
        {"text": "Hey FRIDAY, what is my secret code name?"}, 
        "test"
    ))
    
    print("Waiting 20 seconds for LLM response...")
    await asyncio.sleep(20)
    
    print("\nShutting down...")
    app.supervisor.stop()
    await app_task

if __name__ == "__main__":
    asyncio.run(main())
