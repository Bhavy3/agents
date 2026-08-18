import asyncio
import json
import pytest
from websockets.asyncio.client import connect
from core.events.bus import EventBus
from core.events.event_types import EventType
from core.events.models import Event
from core.api.websocket_worker import WebsocketServerWorker

@pytest.mark.asyncio
async def test_websocket_server_broadcast():
    """Verify the websocket server broadcasts public events to connected clients."""
    bus = EventBus()
    await bus.start()
    
    server = WebsocketServerWorker(bus, host="localhost", port=8766)
    await server.start()
    await asyncio.sleep(0.1) # Wait for server to bind

    async with connect("ws://localhost:8766") as ws:
        # First message should be welcome
        welcome_raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
        welcome = json.loads(welcome_raw)
        assert welcome["event_type"] == "SYSTEM_WELCOME"

        # Publish a public event to the bus
        await bus.publish(Event.create(
            EventType.USER_SPEECH,
            {"status": "final", "text": "hello from test"},
            "test"
        ))

        # Client should receive it
        event_raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
        event_data = json.loads(event_raw)
        
        assert event_data["event_type"] == EventType.USER_SPEECH.value
        assert event_data["payload"]["text"] == "hello from test"

    await server.stop()
    await bus.stop()


@pytest.mark.asyncio
async def test_websocket_server_ingest():
    """Verify the websocket server parses incoming JSON and publishes to EventBus."""
    bus = EventBus()
    await bus.start()
    
    server = WebsocketServerWorker(bus, host="localhost", port=8767)
    await server.start()
    await asyncio.sleep(0.1)

    received_events = []
    async def on_event(e: Event): received_events.append(e)
    bus.subscribe(EventType.USER_SPEECH, on_event)

    async with connect("ws://localhost:8767") as ws:
        # Ignore welcome
        await asyncio.wait_for(ws.recv(), timeout=1.0)

        # Send an event
        client_event = {
            "event_type": EventType.USER_SPEECH.value,
            "payload": {"status": "final", "text": "hello from client"},
            "correlation_id": "test_corr_123"
        }
        await ws.send(json.dumps(client_event))
        
        await asyncio.sleep(0.2)
        
        assert len(received_events) == 1
        assert received_events[0].payload["text"] == "hello from client"
        assert received_events[0].source == "websocket_client"
        assert received_events[0].correlation_id == "test_corr_123"

    await server.stop()
    await bus.stop()
