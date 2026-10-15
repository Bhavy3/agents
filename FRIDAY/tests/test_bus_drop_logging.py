import logging
import pytest
from core.events.bus import EventBus
from core.events.event_types import EventType
from core.events.models import Event


@pytest.mark.asyncio
async def test_dropped_invalid_event_logged_at_warning(caplog):
    bus = EventBus(max_queue_size=10)
    await bus.start()
    try:
        # USER_TEXT_RECEIVED requires 'text' in payload; empty payload is invalid
        invalid_event = Event.create(EventType.USER_TEXT_RECEIVED, payload={})
        with caplog.at_level(logging.DEBUG):
            await bus.publish(invalid_event)

        records = [
            r for r in caplog.records
            if (r.msg == "malformed_event_dropped" or r.getMessage() == "malformed_event_dropped")
        ]
        assert len(records) >= 1
        assert any(r.levelname == "WARNING" for r in records)
    finally:
        await bus.stop()
