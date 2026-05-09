import asyncio
import pytest
import os
from core.events.bus import EventBus
from core.events.event_types import EventType
from core.events.models import Event
from core.memory.memory_worker import MemoryWorker
from core.memory.memory_models import MemoryType


@pytest.mark.asyncio
async def test_memory_persistence_and_recall():
    db_path = "data/memory/test_memory_1.db"
    if os.path.exists(db_path):
        try:
            os.remove(db_path)
        except:
            pass

    bus = EventBus()
    worker = MemoryWorker(bus, db_path=db_path)

    await bus.start()
    await worker.start()
    await asyncio.sleep(0.1)

    # 1. Write request
    await bus.publish(Event.create(
        EventType.MEMORY_WRITE_REQUEST,
        {"type": "preference", "content": "The user likes dark mode."},
        "test"
    ))

    await asyncio.sleep(0.2)
    assert worker._memories_stored == 1

    # 2. Query request
    query_results = []

    async def on_query_result(event):
        query_results.append(event.payload["results"])

    bus.subscribe(EventType.MEMORY_QUERY_RESULT, on_query_result)

    await bus.publish(Event.create(
        EventType.MEMORY_QUERY_REQUEST,
        {"query": "dark mode"},
        "test"
    ))

    await asyncio.sleep(0.2)
    assert len(query_results) == 1
    assert "dark mode" in query_results[0][0]["content"]

    await worker.stop()
    await bus.stop()
    if os.path.exists(db_path):
        try:
            os.remove(db_path)
        except:
            pass


@pytest.mark.asyncio
async def test_memory_validation_rejection():
    db_path = "data/memory/test_memory_2.db"
    if os.path.exists(db_path):
        try: os.remove(db_path)
        except: pass
        
    bus = EventBus()
    worker = MemoryWorker(bus, db_path=db_path)

    await bus.start()
    await worker.start()
    await asyncio.sleep(0.1)

    denied_events = []
    bus.subscribe(EventType.MEMORY_DENIED, lambda e: denied_events.append(e))

    # Secret rejection
    await bus.publish(Event.create(
        EventType.MEMORY_WRITE_REQUEST,
        {"type": "preference", "content": "My secret key is sk-123456789012345678901234567890123456789012345678"},
        "test"
    ))

    await asyncio.sleep(0.2)
    assert len(denied_events) == 1
    assert denied_events[0].payload["reason"] == "forbidden_pattern_detected"

    await worker.stop()
    await bus.stop()
    if os.path.exists(db_path):
        try: os.remove(db_path)
        except: pass


@pytest.mark.asyncio
async def test_memory_ranking_recency():
    db_path = "data/memory/test_memory_3.db"
    if os.path.exists(db_path):
        try: os.remove(db_path)
        except: pass
        
    bus = EventBus()
    worker = MemoryWorker(bus, db_path=db_path)

    await bus.start()
    await worker.start()
    await asyncio.sleep(0.1)

    # Write two similar memories
    await bus.publish(Event.create(
        EventType.MEMORY_WRITE_REQUEST,
        {"type": "preference", "content": "I like blue.", "created_at": 1000},
        "test"
    ))
    await bus.publish(Event.create(
        EventType.MEMORY_WRITE_REQUEST,
        {"type": "preference", "content": "I like red.", "created_at": 2000},
        "test"
    ))

    await asyncio.sleep(0.2)

    query_results = []

    async def on_query_result(event):
        query_results.append(event.payload["results"])

    bus.subscribe(EventType.MEMORY_QUERY_RESULT, on_query_result)

    await bus.publish(Event.create(
        EventType.MEMORY_QUERY_REQUEST,
        {"query": "I like"},
        "test"
    ))

    await asyncio.sleep(0.2)
    assert len(query_results) == 1
    # Red should be first because it's newer (2000 > 1000)
    assert "red" in query_results[0][0]["content"].lower()

    await worker.stop()
    await bus.stop()
    if os.path.exists(db_path):
        try: os.remove(db_path)
        except: pass
