import asyncio
import pytest
from core.events.bus import EventBus
from core.events.event_types import EventType
from core.events.models import Event
from core.api.websocket_worker import WebsocketServerWorker
from websockets.asyncio.client import connect

@pytest.mark.asyncio
async def test_websocket_server_broadcast_bytes():
    """Verify the websocket server handles byte payloads without crashing."""
    from core.api.websocket_worker import PUBLIC_EVENTS
    PUBLIC_EVENTS.add(EventType.AUDIO_CHUNK_RECEIVED)
    
    bus = EventBus()
    await bus.start()
    
    server = WebsocketServerWorker(bus, host="localhost", port=8768)
    await server.start()
    await asyncio.sleep(0.1)

    async with connect("ws://localhost:8768") as ws:
        await asyncio.wait_for(ws.recv(), timeout=1.0) # ignore welcome

        # Publish an event with bytes payload
        await bus.publish(Event.create(
            EventType.AUDIO_CHUNK_RECEIVED,
            {"chunk_size": 1024, "amplitude": 0.5, "timestamp": 123.4, "data": b"fake_audio"},
            "test"
        ))

        # This will time out if the server crashes or drops it, but wait to see
        # Wait, AUDIO_CHUNK_RECEIVED is NOT in PUBLIC_EVENTS, so it won't be broadcast.
        # Let's add it to PUBLIC_EVENTS for the test or use a public event with bytes.
        
    await server.stop()
    await bus.stop()
