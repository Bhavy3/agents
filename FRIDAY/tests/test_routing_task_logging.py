import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock
import pytest

from core.events.event_types import EventType
from core.events.models import Event
from core.orchestrator.conversation import OrchestratorWorker


@pytest.mark.asyncio
async def test_routing_task_failure_logged_at_error(caplog):
    bus = MagicMock()
    bus.publish = AsyncMock()
    worker = OrchestratorWorker(
        event_bus=bus,
        intent_router=MagicMock(),
        streaming_worker=MagicMock(),
    )

    corr_id = "test-corr-id"
    turn_id = "test-turn-id"
    worker._turn_ids_by_correlation_id[corr_id] = turn_id

    async def _failing_task():
        raise RuntimeError("simulated routing failure")

    worker._routing_task = asyncio.create_task(_failing_task())

    event = Event.create(
        EventType.STREAM_COMPLETED,
        payload={"full_text": "sample text"},
        source="test",
        correlation_id=corr_id,
    )

    with caplog.at_level(logging.DEBUG):
        await worker._handle_stream_completed(event)

    records = [
        r for r in caplog.records
        if (r.msg == "routing_task_await_failed_in_stream_completed" or r.getMessage() == "routing_task_await_failed_in_stream_completed")
    ]
    assert len(records) == 1
    assert records[0].levelname == "ERROR"
