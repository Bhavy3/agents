import asyncio
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

from core.events.bus import EventBus
from core.events.event_types import EventType
from core.events.models import Event
from core.memory.memory_index import MemoryIndex
from core.memory.memory_models import MemoryRecord, MemoryType
from core.memory.memory_store import MemoryStore
from core.memory.memory_worker import (
    MemoryWorker,
    compress_memory_content,
    summarize_memory_content,
)
from core.router.llm_fallback import LlmFallbackRouter
from core.router.rules import Intent, IntentName
from core.orchestrator.conversation import OrchestratorWorker
from core.tools.tool_worker import ToolWorker
from unittest.mock import AsyncMock


async def _start_worker(bus, worker):
    await worker.start()
    await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_memory_persistence_and_recall(tmp_path):
    bus = EventBus()
    worker = MemoryWorker(bus, db_path=str(tmp_path / "memory.sqlite"))
    await bus.start()
    await _start_worker(bus, worker)
    writes_completed = []

    async def track_write_completed(event):
        writes_completed.append(event)

    bus.subscribe(EventType.MEMORY_WRITE_COMPLETED, track_write_completed)

    await bus.publish(Event.create(
        EventType.MEMORY_WRITE_REQUEST,
        {"type": "preference", "content": "The user likes dark mode."},
        "test",
    ))
    await bus.drain()
    assert worker._memories_stored == 1
    assert len(writes_completed) == 1

    query_results = []

    async def on_query_result(event):
        query_results.append(event.payload["results"])

    bus.subscribe(EventType.MEMORY_QUERY_RESULT, on_query_result)
    await bus.publish(Event.create(
        EventType.MEMORY_QUERY_REQUEST,
        {"query": "dark mode"},
        "test",
    ))
    await bus.drain()

    assert len(query_results) == 1
    assert "dark mode" in query_results[0][0]["content"]
    assert "metadata" not in query_results[0][0]
    await worker.stop()
    await bus.stop()


@pytest.mark.asyncio
async def test_memory_validation_rejection_emits_one_denial(tmp_path):
    bus = EventBus()
    worker = MemoryWorker(bus, db_path=str(tmp_path / "memory.sqlite"))
    await bus.start()
    await _start_worker(bus, worker)

    denied_events = []

    async def track_denial(event):
        denied_events.append(event)

    bus.subscribe(EventType.MEMORY_DENIED, track_denial)
    await bus.publish(Event.create(
        EventType.MEMORY_WRITE_REQUEST,
        {"type": "preference", "content": "My secret key is sk-123456789012345678901234567890123456789012345678"},
        "test",
    ))
    await bus.drain()

    assert len(denied_events) == 1
    assert denied_events[0].payload["reason"] == "forbidden_pattern_detected"
    await worker.stop()
    await bus.stop()


@pytest.mark.asyncio
async def test_memory_rejects_empty_oversized_and_secret_metadata(tmp_path):
    bus = EventBus()
    worker = MemoryWorker(bus, db_path=str(tmp_path / "memory.sqlite"))
    await bus.start()
    await _start_worker(bus, worker)
    denied_events = []

    async def track_denial(event):
        denied_events.append(event)

    bus.subscribe(EventType.MEMORY_DENIED, track_denial)
    writes = (
        {"type": "preference", "content": "   "},
        {"type": "preference", "content": "x" * 2001},
        {"type": "preference", "content": "Safe content.", "metadata": {"nested": {"key": "token=hidden-secret"}}},
        {"type": "approved_fact", "content": "The user has a personal preference."},
    )
    for payload in writes:
        await bus.publish(Event.create(EventType.MEMORY_WRITE_REQUEST, payload, "test"))
    await bus.drain()

    assert len(denied_events) == len(writes)
    assert {event.payload["reason"].split(":")[0] for event in denied_events} == {
        "content_length_violation",
        "forbidden_pattern_detected",
        "explicit_approval_required",
    }
    await worker.stop()
    await bus.stop()


def _record(
    record_id: str,
    content: str,
    *,
    memory_type: MemoryType = MemoryType.PREFERENCE,
    created_at: float | None = None,
    updated_at: float | None = None,
    confidence: float = 1.0,
    approved: bool = False,
) -> MemoryRecord:
    now = time.time()
    return MemoryRecord(
        id=record_id,
        type=memory_type,
        content=content,
        created_at=created_at if created_at is not None else now,
        updated_at=updated_at if updated_at is not None else now,
        source="test",
        confidence=confidence,
        explicit_user_approved=approved,
    )


def test_memory_ranking_prefers_relevant_older_memory_to_unrelated_newer():
    index = MemoryIndex()
    now = time.time()
    relevant = _record(
        "relevant",
        "I use Python typing tools for development.",
        updated_at=now - 365 * 24 * 60 * 60,
    )
    unrelated_new = _record("new", "The meeting is next Thursday.", updated_at=now)

    ranked = index.rank("Python typing tools", [unrelated_new, relevant])

    assert [record.id for record in ranked] == ["relevant", "new"]


def test_memory_ranking_exact_phrase_and_approval_are_deterministic():
    index = MemoryIndex()
    now = time.time()
    exact = _record("exact", "I prefer dark mode for this editor.", updated_at=now)
    partial = _record("partial", "Prefer it in dark rooms and switch mode.", updated_at=now)
    approved = _record(
        "approved",
        exact.content,
        memory_type=MemoryType.APPROVED_FACT,
        updated_at=now,
        approved=True,
    )

    first_rank = index.rank("prefer dark mode", [partial, exact, approved])
    second_rank = index.rank("prefer dark mode", [approved, exact, partial])

    assert index.rank("prefer dark mode", [partial, exact])[0].id == "exact"
    assert [record.id for record in first_rank] == [record.id for record in second_rank]
    approved_rank = index.rank("prefer dark mode", [exact, approved])
    assert approved_rank[0].id == "approved"


def test_memory_relevance_matches_short_typos_and_plural_forms():
    index = MemoryIndex()
    favorite_movie = _record(
        "favorite-movie",
        "My favorite movie is Fast and Furious 8.",
    )
    unrelated = _record("unrelated", "The meeting is next Thursday.")

    assert index.text_is_relevant("whats my fev movie", favorite_movie.content)
    assert index.text_is_relevant("movie", "My favorite movies are action films.")
    assert index.rank("fev movie", [unrelated, favorite_movie])[0].id == "favorite-movie"


def test_memory_relevance_decay_is_bounded_and_deterministic():
    index = MemoryIndex()
    now = time.time()
    newer = _record("new", "An unrelated note.", updated_at=now)
    older = _record("old", "Another unrelated note.", updated_at=now - 365 * 86400)

    assert index.relevance_decay(0) == 1.0
    assert index.relevance_decay(365 * 86400) == index.MIN_RELEVANCE_DECAY
    assert [record.id for record in index.rank("Python", [older, newer])] == ["new", "old"]


def test_memory_compression_normalizes_and_deduplicates_without_changing_short_text():
    short = "I prefer dark mode."
    assert compress_memory_content(short) == short
    assert compress_memory_content("I   prefer dark mode.\nI prefer dark mode.") == short


def test_memory_compression_reduces_long_repeated_content():
    repeated = "My goal is to ship reliable software. " * 100

    compressed = compress_memory_content(repeated)

    assert compressed == "My goal is to ship reliable software."
    assert len(compressed) < 2000


def test_memory_summary_is_bounded_and_extractive():
    source = (
        "Bhavy uses Friday as a local assistant. "
        "The user's goal is to build a local assistant. "
        "The user must keep data on this computer. "
        "The plan includes several maintenance activities. "
        + "The meeting happened on Tuesday. " * 80
    )

    summary = summarize_memory_content(source, max_length=180)

    assert len(summary) <= 180
    assert "Bhavy uses Friday as a local assistant." in summary
    assert "goal is to build a local assistant" in summary
    assert "must keep data on this computer" in summary
    assert "invented" not in summary


@pytest.mark.asyncio
async def test_memory_write_ids_are_collision_safe_and_explicit_ids_update(tmp_path):
    bus = EventBus()
    worker = MemoryWorker(bus, db_path=str(tmp_path / "memory.sqlite"))
    await bus.start()
    await _start_worker(bus, worker)

    for content in ("first note", "second note"):
        await bus.publish(Event.create(
            EventType.MEMORY_WRITE_REQUEST,
            {"type": "preference", "content": content},
            "test",
        ))
    await bus.publish(Event.create(
        EventType.MEMORY_WRITE_REQUEST,
        {
            "id": "explicit",
            "type": "approved_fact",
            "content": "The user prefers local storage.",
            "explicit_user_approved": True,
        },
        "test",
    ))
    await bus.publish(Event.create(
        EventType.MEMORY_WRITE_REQUEST,
        {
            "id": "explicit",
            "type": "approved_fact",
            "content": "The user requires local storage.",
            "explicit_user_approved": True,
        },
        "test",
    ))
    await bus.drain()

    records = await worker.store.query()
    assert len(records) == 3
    explicit = next(record for record in records if record.id == "explicit")
    assert explicit.content == "The user requires local storage."
    assert explicit.explicit_user_approved is True
    await worker.stop()
    await bus.stop()


@pytest.mark.asyncio
async def test_memory_survives_worker_restart_and_new_store_instance(tmp_path):
    db_path = str(tmp_path / "persistent.sqlite")
    first_bus = EventBus()
    first_worker = MemoryWorker(first_bus, db_path=db_path)
    await first_bus.start()
    await _start_worker(first_bus, first_worker)
    await first_bus.publish(Event.create(
        EventType.MEMORY_WRITE_REQUEST,
        {
            "id": "persistent-fact",
            "type": "approved_fact",
            "content": "The user prefers local SQLite storage.",
            "explicit_user_approved": True,
        },
        "test",
    ))
    await first_bus.drain()
    await first_worker.stop()
    await first_bus.stop()

    second_worker = MemoryWorker(EventBus(), db_path=db_path)
    records = await second_worker.store.query(MemoryType.APPROVED_FACT)

    assert len(records) == 1
    assert records[0].id == "persistent-fact"
    assert records[0].explicit_user_approved is True
    process_check = subprocess.run(
        [
            sys.executable,
            "-c",
            "import asyncio, sys; from core.memory.memory_store import MemoryStore; "
            "from core.memory.memory_models import MemoryType; "
            "rows = asyncio.run(MemoryStore(sys.argv[1]).query(MemoryType.APPROVED_FACT)); "
            "print(rows[0].content if rows else '')",
            db_path,
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert "local SQLite storage" in process_check.stdout


@pytest.mark.asyncio
async def test_conversation_turn_injects_bounded_relevant_memory_context(tmp_path):
    bus = EventBus()
    worker = MemoryWorker(bus, db_path=str(tmp_path / "memory.sqlite"))
    await bus.start()
    await _start_worker(bus, worker)
    for index in range(4):
        await bus.publish(Event.create(
            EventType.MEMORY_WRITE_REQUEST,
            {
                "type": "preference",
                "content": f"Python typing preference {index}. " + "Keep the local design and constraints. " * 8,
            },
            "test",
        ))
    await bus.publish(Event.create(
        EventType.MEMORY_WRITE_REQUEST,
        {
            "type": "preference",
            "content": "I prefer Python typing for this project.",
            "metadata": {"internal_id": "must not be included in prompts"},
        },
        "test",
    ))
    await bus.publish(Event.create(
        EventType.MEMORY_WRITE_REQUEST,
        {"type": "preference", "content": "I prefer mountain biking."},
        "test",
    ))
    await bus.drain()

    router = AsyncMock()
    router.route.return_value = Intent(IntentName.CHAT, 0.99, {"response_text": "Here is the answer."})
    orchestrator = OrchestratorWorker(bus, router, AsyncMock())
    task = asyncio.create_task(orchestrator.run())
    await asyncio.sleep(0)

    await bus.publish(Event.create(
        EventType.USER_TEXT_RECEIVED,
        {"text": "Which Python typing approach should I use?"},
        "test",
    ))
    for _ in range(100):
        if router.route.await_count:
            break
        await asyncio.sleep(0.01)

    assert router.route.await_count == 1
    chat_instructions = router.route.await_args.kwargs["chat_instructions"]
    assert "I prefer Python typing for this project." in chat_instructions
    assert "mountain biking" not in chat_instructions
    assert "internal_id" not in chat_instructions
    memory_context = chat_instructions.split("System Memory/Context:\n", 1)[1]
    assert len(memory_context) <= 1200

    await orchestrator.stop()
    await task
    await worker.stop()
    await bus.stop()


async def _run_memory_routing_case(tmp_path, query: str, saved_content: str | None):
    bus = EventBus()
    await bus.start()
    worker = MemoryWorker(bus, db_path=str(tmp_path / "memory-routing.sqlite"))
    await _start_worker(bus, worker)

    router = AsyncMock()
    router.route.return_value = Intent(
        IntentName.SEARCH_WEB,
        0.99,
        {"query": query},
    )
    orchestrator = OrchestratorWorker(bus, router, AsyncMock())
    responses = []
    actions = []
    result_received = asyncio.Event()

    async def track_response(event):
        responses.append(event)
        result_received.set()

    async def track_action(event):
        actions.append(event)
        result_received.set()

    bus.subscribe(EventType.RESPONSE_READY, track_response)
    bus.subscribe(EventType.ACTION_REQUESTED, track_action)
    orchestrator_task = asyncio.create_task(orchestrator.run())
    await asyncio.sleep(0.05)

    try:
        if saved_content:
            await bus.publish(Event.create(
                EventType.MEMORY_WRITE_REQUEST,
                {
                    "type": "approved_fact",
                    "content": saved_content,
                    "explicit_user_approved": True,
                },
                "test",
            ))
            await bus.drain()

        await bus.publish(Event.create(
            EventType.USER_TEXT_RECEIVED,
            {"text": query},
            "test",
        ))
        await asyncio.wait_for(result_received.wait(), timeout=2)
        result = (list(responses), list(actions), router)

        if actions:
            await bus.publish(Event.create(
                EventType.ACTION_FAILED,
                {"tool_name": "search_web", "error": "test cleanup"},
                "test",
                actions[0].correlation_id,
            ))
            await bus.drain()
        return result
    finally:
        await orchestrator.stop()
        await orchestrator_task
        await worker.stop()
        await bus.stop()


@pytest.mark.asyncio
async def test_personal_typo_recall_uses_saved_favorite_without_search(tmp_path):
    responses, actions, router = await _run_memory_routing_case(
        tmp_path,
        "whats my fev movie",
        "My favorite movie is Fast and Furious 8.",
    )

    assert len(responses) == 1
    assert responses[0].payload["text"] == "You told me: My favorite movie is Fast and Furious 8."
    assert actions == []
    router.route.assert_not_awaited()


@pytest.mark.asyncio
async def test_non_personal_web_search_still_routes_to_search(tmp_path):
    query = "search the web for BMW M8 top speed"

    responses, actions, router = await _run_memory_routing_case(tmp_path, query, None)

    assert responses == []
    assert len(actions) == 1
    assert actions[0].payload["intent"] == "search_web"
    router.route.assert_awaited_once()


@pytest.mark.asyncio
async def test_personal_query_with_empty_memory_falls_through_to_search(tmp_path):
    query = "whats my fev movie"

    responses, actions, router = await _run_memory_routing_case(tmp_path, query, None)

    assert responses == []
    assert len(actions) == 1
    assert actions[0].payload["intent"] == "search_web"
    router.route.assert_awaited_once()


@pytest.mark.asyncio
async def test_unsaved_memory_question_receives_accurate_memory_guidance(tmp_path):
    bus = EventBus()
    worker = MemoryWorker(bus, db_path=str(tmp_path / "memory.sqlite"))
    await bus.start()
    await _start_worker(bus, worker)

    write_requests = []
    responses = []

    async def track_write(event):
        write_requests.append(event)

    async def track_response(event):
        responses.append(event)

    bus.subscribe(EventType.MEMORY_WRITE_REQUEST, track_write)
    bus.subscribe(EventType.RESPONSE_READY, track_response)
    ollama = AsyncMock()
    ollama.model = "test-model"
    ollama.generate.return_value = (
        '{"intent":"chat","confidence":0.99,"parameters":{}}',
        SimpleNamespace(success=True, latency_seconds=0.01, model="test-model"),
    )
    streaming_worker = AsyncMock()
    streaming_worker.stream_reasoning.return_value = "I don't have that saved yet."
    router = LlmFallbackRouter(
        ollama_client=ollama,
        event_bus=bus,
        streaming_worker=streaming_worker,
    )
    orchestrator = OrchestratorWorker(bus, router, streaming_worker)
    task = asyncio.create_task(orchestrator.run())
    await asyncio.sleep(0)

    await bus.publish(Event.create(
        EventType.USER_TEXT_RECEIVED,
        {"text": "Do you remember my favorite car is BMW M8?"},
        "test_cli",
    ))
    for _ in range(100):
        if responses:
            break
        await asyncio.sleep(0.01)

    assert len(responses) == 1
    assert responses[0].payload["text"] == "I don't have that saved yet."
    streaming_worker.stream_reasoning.assert_awaited_once()
    final_prompt = streaming_worker.stream_reasoning.await_args.args[0]
    assert "retain information long-term" in final_prompt
    assert "only when the user explicitly asks" in final_prompt
    assert "Never claim that you cannot remember past conversations" in final_prompt
    assert "say you do not have it saved" in final_prompt
    assert "offer to remember it now" in final_prompt
    assert "System Memory/Context:" not in final_prompt
    assert write_requests == []
    assert await worker.store.query(MemoryType.APPROVED_FACT) == []

    await orchestrator.stop()
    await task
    await worker.stop()
    await bus.stop()


@pytest.mark.asyncio
async def test_explicit_remember_utterance_writes_memory_without_routing_to_tools(tmp_path, caplog):
    bus = EventBus()
    worker = MemoryWorker(bus, db_path=str(tmp_path / "memory.sqlite"))
    tool_worker = ToolWorker(bus)
    await bus.start()
    await _start_worker(bus, worker)
    await _start_worker(bus, tool_worker)

    write_requests = []

    async def track_write(event):
        write_requests.append(event)

    bus.subscribe(EventType.MEMORY_WRITE_REQUEST, track_write)
    action_requests = []
    responses = []

    async def track_action(event):
        action_requests.append(event)

    async def track_response(event):
        responses.append(event)

    bus.subscribe(EventType.ACTION_REQUESTED, track_action)
    bus.subscribe(EventType.RESPONSE_READY, track_response)
    router = AsyncMock()
    router.route.return_value = Intent(IntentName.WRITE_TEXT_FILE, 0.99, {
        "filename": "must-not-be-called.txt",
        "content": "wrongly classified",
    })
    orchestrator = OrchestratorWorker(bus, router, AsyncMock())
    orchestrator_task = asyncio.create_task(orchestrator.run())
    await asyncio.sleep(0)

    await bus.publish(Event.create(
        EventType.USER_TEXT_RECEIVED,
        {"text": "Remember that my favorite color is blue."},
        "test_cli",
    ))
    for _ in range(100):
        if write_requests and responses:
            break
        await asyncio.sleep(0.01)
    await bus.drain()

    records = await worker.store.query(MemoryType.APPROVED_FACT)
    assert router.route.await_count == 0
    assert len(write_requests) == 1
    assert len(responses) == 1
    assert responses[0].payload["text"] == "I'll remember that."
    assert action_requests == []
    assert not any(record.message == "tool_execution_failed" for record in caplog.records)
    assert write_requests[0].payload["content"] == "my favorite color is blue."
    assert write_requests[0].payload["explicit_user_approved"] is True
    assert write_requests[0].payload["source"] == "explicit_user_request"
    assert len(records) == 1
    assert records[0].content == "my favorite color is blue."
    assert records[0].explicit_user_approved is True

    for _ in range(100):
        if orchestrator.active_turn_id is None:
            break
        await asyncio.sleep(0.01)
    await bus.publish(Event.create(
        EventType.USER_TEXT_RECEIVED,
        {"text": "I am asking a regular question about dark mode."},
        "test_cli",
    ))
    for _ in range(100):
        if router.route.await_count >= 2 and orchestrator.active_turn_id is None:
            break
        await asyncio.sleep(0.01)
    await bus.drain()
    assert len(write_requests) == 1
    assert len(await worker.store.query(MemoryType.APPROVED_FACT)) == 1

    await orchestrator.stop()
    await orchestrator_task
    await worker.stop()
    await tool_worker.stop()
    await bus.stop()


@pytest.mark.asyncio
async def test_memory_summary_write_uses_validation_and_bounded_storage(tmp_path):
    bus = EventBus()
    worker = MemoryWorker(bus, db_path=str(tmp_path / "memory.sqlite"))
    await bus.start()
    await _start_worker(bus, worker)

    await bus.publish(Event.create(
        EventType.MEMORY_WRITE_REQUEST,
        {
            "type": "conversation_summary",
            "content": "The user's goal is reliability. The user must keep data local. " * 30,
            "explicit_user_approved": True,
        },
        "test",
    ))
    await bus.drain()

    summaries = await worker.store.query(MemoryType.CONVERSATION_SUMMARY)
    assert len(summaries) == 1
    assert len(summaries[0].content) <= 1200
    assert "goal is reliability" in summaries[0].content
    assert "must keep data local" in summaries[0].content

    await worker.stop()
    await bus.stop()
