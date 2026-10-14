"""
Voice Contract Tests

Validate the TTS/Orchestrator/LLM streaming event flow without hardware.
Drives real OrchestratorWorker + TtsWorker with mocked LLM and web search.

Six conversation scenarios are covered:
1. Normal chat turn
2. Personal-memory turn (answered from memory, router bypassed)
3. Web-search turn (acknowledgment + deferred result)
4. Search turn interrupted before the result arrives
5. Explicit "remember that..." turn
6. Two consecutive turns back to back

Completed-turn scenarios assert:
- Exactly one TTS_STREAM_END per turn, with the correct turn_id
- ASSISTANT_RESPONSE_COMPLETED fires only after all ASSISTANT_RESPONSE_PARTIAL chunks
- active_speaker returns to "user" afterward

The interrupted-search scenario separately asserts turn cleanup and that the
interrupted turn emits no stale response events. A seventh router-exception
regression asserts one deterministic degraded response, traceback logging, and
routing/turn cleanup. A separate late-stream regression covers completions for
turns whose correlation has been invalidated.

These tests use the real TtsWorker with mocked synthesis, but do not instantiate
TtsOutputProcessor or assert playback-completion duplication or safety-net
counters. Playback completion and safety-net counters are tested separately.
"""

import asyncio
import pytest
from typing import Any
from unittest.mock import MagicMock, patch
from dataclasses import dataclass, field

from core.events.bus import EventBus
from core.events.event_types import EventType
from core.events.models import Event
from core.orchestrator.conversation import DEGRADED_ROUTER_MESSAGE, OrchestratorWorker
from core.audio.tts import TtsWorker
from core.router.rules import Intent, IntentName
import uuid
import time


@dataclass
class EventSnapshot:
    """Captures a moment-in-time snapshot of all events."""
    turn_id: str
    turn_type: str
    events_by_type: dict[str, list[Event]] = field(default_factory=dict)
    violations: list[str] = field(default_factory=list)


class EventRecorder:
    """Captures all events for post-hoc analysis."""
    
    def __init__(self):
        self.events: list[Event] = []
        self.lock = asyncio.Lock()
    
    async def record(self, event: Event) -> None:
        async with self.lock:
            self.events.append(event)
    
    async def get_by_type(self, event_type: EventType) -> list[Event]:
        async with self.lock:
            return [e for e in self.events if e.event_type == event_type]
    
    async def get_by_turn(self, turn_id: str) -> list[Event]:
        async with self.lock:
            return [e for e in self.events if e.payload.get("turn_id") == turn_id]
    
    async def clear(self) -> None:
        async with self.lock:
            self.events.clear()
    
    async def snapshot(self) -> list[Event]:
        async with self.lock:
            return list(self.events)


@pytest.fixture
async def event_bus():
    bus = EventBus()
    await bus.start()
    yield bus
    await bus.stop()


@pytest.fixture
async def recorder():
    return EventRecorder()


@pytest.fixture
async def mock_llm():
    """Mock streaming LLM worker."""
    class MockLLM:
        def __init__(self, event_bus):
            self.event_bus = event_bus
            self.cancelled = False
        
        async def stream_response(self, prompt: str, correlation_id: str | None = None) -> str:
            correlation_id = correlation_id or str(uuid.uuid4())
            stream_id = str(uuid.uuid4())
            start_time = time.perf_counter()
            
            if self.cancelled:
                return ""
            
            # Emit stream started
            await self.event_bus.publish(Event.create(
                EventType.STREAM_STARTED,
                {"stream_id": stream_id, "model": "test-model"},
                "mock_llm",
                correlation_id
            ))
            
            # Emit chunks
            response_text = "This is a test response to your question about the weather and other topics."
            words = response_text.split()
            
            for index, word in enumerate(words):
                if self.cancelled:
                    await self.event_bus.publish(Event.create(
                        EventType.STREAM_CANCELLED,
                        {"stream_id": stream_id, "reason": "user_interruption"},
                        "mock_llm",
                        correlation_id
                    ))
                    return ""
                
                await self.event_bus.publish(Event.create(
                    EventType.STREAM_CHUNK,
                    {"stream_id": stream_id, "chunk": word + " ", "index": index},
                    "mock_llm",
                    correlation_id
                ))
                await asyncio.sleep(0.01)
            
            if not self.cancelled:
                await self.event_bus.publish(Event.create(
                    EventType.STREAM_COMPLETED,
                    {
                        "stream_id": stream_id,
                        "full_text": response_text,
                        "chunk_count": len(words),
                        "duration": time.perf_counter() - start_time,
                        "cancelled": False,
                        "timed_out": False,
                        "degraded_mode": False,
                    },
                    "mock_llm",
                    correlation_id
                ))
            return response_text

        async def stream_reasoning(self, prompt: str, correlation_id: str | None = None) -> str:
            return await self.stream_response(prompt, correlation_id)
        
        def cancel_all(self) -> None:
            self.cancelled = True
    
    return MockLLM


@pytest.fixture
async def orchestrator_worker(event_bus, mock_llm):
    """Create an OrchestratorWorker with mocked router."""
    with patch('core.router.intent_router.IntentRouter'):
        intent_router = MagicMock()
        llm_worker = mock_llm(event_bus)
        
        orchestrator = OrchestratorWorker(
            event_bus=event_bus,
            intent_router=intent_router,
            streaming_worker=llm_worker,
            enable_presence_ack=False,
        )
        
        # Default router behavior: return CHAT intent
        async def mock_route(text, **kwargs):
            response_text = await llm_worker.stream_reasoning(text, kwargs.get("correlation_id"))
            return Intent(
                IntentName.CHAT,
                1.0,
                {"response_text": response_text},
                source="ollama_reasoning",
            )
        
        intent_router.route = mock_route
        
        # Run the orchestrator but make sure it's scheduled
        orchestrator_task = asyncio.create_task(orchestrator.run())
        
        # Wait briefly for orchestrator to be ready
        await asyncio.sleep(0.2)
        
        yield orchestrator, llm_worker
        
        # Cleanup
        await orchestrator.stop()
        orchestrator_task.cancel()
        try:
            await orchestrator_task
        except asyncio.CancelledError:
            pass


@pytest.fixture
async def tts_worker_instance(event_bus):
    """Create a TtsWorker with mocked Piper."""
    with patch('core.audio.tts.PiperVoice'):
        tts = TtsWorker(event_bus)
        tts._is_initialized = True
        tts.voice = MagicMock()
        tts.voice.synthesize = MagicMock(return_value=[
            MagicMock(audio_int16_bytes=b'\x00\x00' * 160),
            MagicMock(audio_int16_bytes=b'\x00\x00' * 160),
        ])
        
        # Run the TTS worker
        tts_task = asyncio.create_task(tts.run())
        
        # Give it time to subscribe
        await asyncio.sleep(0.1)
        
        yield tts
        
        # Cleanup
        await tts.stop()
        tts_task.cancel()
        try:
            await tts_task
        except asyncio.CancelledError:
            pass


async def subscribe_recorder(event_bus: EventBus, recorder: EventRecorder) -> None:
    """Subscribe recorder to all event types."""
    for event_type in EventType:
        event_bus.subscribe(event_type, recorder.record)


async def wait_for_event(
    recorder: EventRecorder,
    event_type: EventType,
    turn_id: str | None = None,
) -> Event:
    async def find_event() -> Event:
        while True:
            events = await recorder.get_by_type(event_type)
            for event in events:
                if turn_id is None or event.payload.get("turn_id") == turn_id:
                    return event
            await asyncio.sleep(0.01)

    return await asyncio.wait_for(find_event(), timeout=5.0)


async def wait_for_event_count(
    recorder: EventRecorder,
    event_type: EventType,
    count: int,
) -> list[Event]:
    async def find_events() -> list[Event]:
        while True:
            events = await recorder.get_by_type(event_type)
            if len(events) >= count:
                return events
            await asyncio.sleep(0.01)

    return await asyncio.wait_for(find_events(), timeout=5.0)


async def wait_for_turn_cleanup(orchestrator: OrchestratorWorker, turn_id: str) -> None:
    async def wait_until_cleaned() -> None:
        while orchestrator.active_turn_id == turn_id or orchestrator._routing_task is not None:
            await asyncio.sleep(0.01)

    await asyncio.wait_for(wait_until_cleaned(), timeout=5.0)


async def validate_turn_contract(
    turn_id: str,
    turn_type: str,
    recorder: EventRecorder,
    orchestrator_worker: OrchestratorWorker,
) -> EventSnapshot:
    """Validate contract invariants for a single turn."""
    turn_events = await recorder.get_by_turn(turn_id)
    
    snapshot = EventSnapshot(turn_id=turn_id, turn_type=turn_type)
    
    # Group by type
    event_counts = {}
    for event in turn_events:
        event_type = event.event_type
        event_counts[event_type] = event_counts.get(event_type, 0) + 1
        if event_type not in snapshot.events_by_type:
            snapshot.events_by_type[event_type] = []
        snapshot.events_by_type[event_type].append(event)
    
    # Contract 1: Exactly one TTS_STREAM_END per turn
    stream_end_count = event_counts.get(EventType.TTS_STREAM_END, 0)
    if stream_end_count != 1:
        snapshot.violations.append(f"Expected 1 TTS_STREAM_END, got {stream_end_count}")
    
    # Contract 2: Exactly one ASSISTANT_RESPONSE_COMPLETED per turn
    response_completed_count = event_counts.get(EventType.ASSISTANT_RESPONSE_COMPLETED, 0)
    if response_completed_count != 1:
        snapshot.violations.append(f"Expected 1 ASSISTANT_RESPONSE_COMPLETED, got {response_completed_count}")
    
    # Contract 3: ASSISTANT_RESPONSE_COMPLETED after all ASSISTANT_RESPONSE_PARTIAL
    partial_count = event_counts.get(EventType.ASSISTANT_RESPONSE_PARTIAL, 0)
    if partial_count > 0 and response_completed_count > 0:
        partial_events = snapshot.events_by_type.get(EventType.ASSISTANT_RESPONSE_PARTIAL, [])
        completed_events = snapshot.events_by_type.get(EventType.ASSISTANT_RESPONSE_COMPLETED, [])
        if partial_events and completed_events:
            if completed_events[0].created_at < partial_events[-1].created_at:
                snapshot.violations.append("ASSISTANT_RESPONSE_COMPLETED fired before final ASSISTANT_RESPONSE_PARTIAL")
    
    # Contract 4: active_speaker returns to "user" after turn ends
    turn_ended_events = snapshot.events_by_type.get(EventType.CONVERSATION_TURN_ENDED, [])
    if turn_ended_events:
        if orchestrator_worker.active_speaker not in [None, "user"]:
            snapshot.violations.append(f"active_speaker should be None or 'user' after turn, got '{orchestrator_worker.active_speaker}'")
    
    return snapshot


# ==================== TURN TYPE TESTS ====================

@pytest.mark.asyncio
async def test_normal_chat_turn(event_bus, recorder, orchestrator_worker, tts_worker_instance):
    """Test: Normal chat turn - user asks, LLM responds, TTS plays."""
    orchestrator, llm = orchestrator_worker
    tts = tts_worker_instance
    
    # Give workers time to initialize
    await asyncio.sleep(0.5)
    
    await subscribe_recorder(event_bus, recorder)
    
    # Simulate user input
    correlation_id = str(uuid.uuid4())
    segment_id = str(uuid.uuid4())
    await event_bus.publish(Event.create(
        EventType.STT_FINAL_TRANSCRIPT,
        {
            "segment_id": segment_id,
            "text": "What is the weather today?",
            "duration": 2.5,
            "confidence": 0.95
        },
        "stt",
        correlation_id
    ))
    
    # Wait for the response and queued TTS end marker
    completed = await wait_for_event(recorder, EventType.ASSISTANT_RESPONSE_COMPLETED)
    await wait_for_event(recorder, EventType.TTS_STREAM_END, completed.payload["turn_id"])
    
    # Get the turn ID from turn start event
    turn_started = await recorder.get_by_type(EventType.CONVERSATION_TURN_STARTED)
    assert len(turn_started) >= 1, f"Expected at least one turn started, got {len(turn_started)}"
    
    turn_id = turn_started[0].payload.get("turn_id")
    
    # Validate contract
    snapshot = await validate_turn_contract(turn_id, "normal_chat", recorder, orchestrator)
    
    # Report results
    assert not snapshot.violations, f"Contract violations: {snapshot.violations}"
    assert orchestrator.active_speaker in [None, "user"], f"active_speaker should be None or 'user', got '{orchestrator.active_speaker}'"


@pytest.mark.asyncio
async def test_router_exception_degrades_once_and_cleans_turn(
    event_bus,
    recorder,
    orchestrator_worker,
    caplog,
):
    orchestrator, _ = orchestrator_worker

    async def failing_route(text: str, **kwargs: Any) -> Intent:
        raise RuntimeError("router unavailable")

    orchestrator.intent_router.route = failing_route
    await subscribe_recorder(event_bus, recorder)

    correlation_id = str(uuid.uuid4())
    await event_bus.publish(Event.create(
        EventType.STT_FINAL_TRANSCRIPT,
        {
            "segment_id": str(uuid.uuid4()),
            "text": "Tell me something",
            "duration": 1.5,
            "confidence": 0.95,
        },
        "stt",
        correlation_id,
    ))

    response = await wait_for_event(recorder, EventType.RESPONSE_READY)
    turn_id = response.payload["turn_id"]
    await wait_for_turn_cleanup(orchestrator, turn_id)

    degraded_responses = [
        event
        for event in await recorder.get_by_type(EventType.RESPONSE_READY)
        if event.payload.get("turn_id") == turn_id
    ]
    assert len(degraded_responses) == 1
    assert degraded_responses[0].payload["text"] == DEGRADED_ROUTER_MESSAGE
    assert orchestrator.active_turn_id is None
    assert orchestrator._routing_task is None
    assert any(
        record.getMessage() == "intent_router_route_failed" and record.exc_info
        for record in caplog.records
    )


@pytest.mark.asyncio
async def test_late_stream_completion_is_ignored_after_turn_is_invalidated(
    event_bus,
    recorder,
    orchestrator_worker,
):
    orchestrator, _ = orchestrator_worker
    await subscribe_recorder(event_bus, recorder)

    correlation_id = str(uuid.uuid4())
    turn_id = "interrupted-turn"
    release_routing = asyncio.Event()

    async def pending_routing() -> None:
        await release_routing.wait()

    routing_task = asyncio.create_task(pending_routing())
    async with orchestrator._state_lock:
        orchestrator.active_turn_id = turn_id
        orchestrator._routing_task = routing_task
        orchestrator._turn_ids_by_correlation_id = {correlation_id: turn_id}

    completion_task = asyncio.create_task(orchestrator._handle_stream_completed(Event.create(
        EventType.STREAM_COMPLETED,
        {"full_text": "stale response"},
        "mock_llm",
        correlation_id,
    )))
    await asyncio.sleep(0)

    async with orchestrator._state_lock:
        orchestrator._turn_ids_by_correlation_id.pop(correlation_id, None)
    release_routing.set()
    await completion_task

    completed = [
        event
        for event in await recorder.get_by_type(EventType.ASSISTANT_RESPONSE_COMPLETED)
        if event.payload.get("turn_id") == turn_id
    ]
    assert completed == []
    assert all(item.get("content") != "stale response" for item in orchestrator.context)


@pytest.mark.asyncio
async def test_explicit_remember_turn(event_bus, recorder, orchestrator_worker, tts_worker_instance):
    """Test: Explicit 'remember that...' turn."""
    orchestrator, llm = orchestrator_worker
    tts = tts_worker_instance
    
    await subscribe_recorder(event_bus, recorder)
    
    # Simulate user input with explicit memory request
    correlation_id = str(uuid.uuid4())
    segment_id = str(uuid.uuid4())
    await event_bus.publish(Event.create(
        EventType.STT_FINAL_TRANSCRIPT,
        {
            "segment_id": segment_id,
            "text": "Remember that I love pizza",
            "duration": 2.2,
            "confidence": 0.93
        },
        "stt",
        correlation_id
    ))
    
    completed = await wait_for_event(recorder, EventType.ASSISTANT_RESPONSE_COMPLETED)
    await wait_for_event(recorder, EventType.TTS_STREAM_END, completed.payload["turn_id"])
    
    turn_event = await wait_for_event(recorder, EventType.CONVERSATION_TURN_STARTED)
    turn_id = turn_event.payload.get("turn_id")
    
    # Check that memory write was requested
    memory_writes = await recorder.get_by_type(EventType.MEMORY_WRITE_REQUEST)
    assert len(memory_writes) > 0, "Expected MEMORY_WRITE_REQUEST for explicit remember"
    
    # Validate contract
    snapshot = await validate_turn_contract(turn_id, "explicit_remember", recorder, orchestrator)
    
    assert not snapshot.violations, f"Contract violations: {snapshot.violations}"


@pytest.mark.asyncio
async def test_consecutive_turns_back_to_back(event_bus, recorder, orchestrator_worker, tts_worker_instance):
    """Test: Two consecutive turns back to back."""
    orchestrator, llm = orchestrator_worker
    tts = tts_worker_instance
    
    await subscribe_recorder(event_bus, recorder)
    
    # First turn
    correlation_id_1 = str(uuid.uuid4())
    segment_id_1 = str(uuid.uuid4())
    await event_bus.publish(Event.create(
        EventType.STT_FINAL_TRANSCRIPT,
        {
            "segment_id": segment_id_1,
            "text": "Hello, how are you?",
            "duration": 1.5,
            "confidence": 0.98
        },
        "stt",
        correlation_id_1
    ))
    
    first_completed = await wait_for_event(recorder, EventType.ASSISTANT_RESPONSE_COMPLETED)
    await wait_for_event(recorder, EventType.TTS_STREAM_END, first_completed.payload["turn_id"])
    
    # Second turn
    correlation_id_2 = str(uuid.uuid4())
    segment_id_2 = str(uuid.uuid4())
    await event_bus.publish(Event.create(
        EventType.STT_FINAL_TRANSCRIPT,
        {
            "segment_id": segment_id_2,
            "text": "What time is it?",
            "duration": 1.2,
            "confidence": 0.97
        },
        "stt",
        correlation_id_2
    ))
    
    turn_started_events = await wait_for_event_count(
        recorder,
        EventType.CONVERSATION_TURN_STARTED,
        2,
    )
    second_turn_id = turn_started_events[1].payload.get("turn_id")
    await wait_for_event(recorder, EventType.ASSISTANT_RESPONSE_COMPLETED, second_turn_id)
    await wait_for_event(recorder, EventType.TTS_STREAM_END, second_turn_id)
    
    # Get turn IDs
    turn_started_events = await recorder.get_by_type(EventType.CONVERSATION_TURN_STARTED)
    assert len(turn_started_events) >= 2, f"Expected at least 2 turns started, got {len(turn_started_events)}"
    
    # Validate both turns
    for i, turn_event in enumerate(turn_started_events[:2]):
        turn_id = turn_event.payload.get("turn_id")
        snapshot = await validate_turn_contract(turn_id, f"consecutive_{i+1}", recorder, orchestrator)
        
        assert not snapshot.violations, f"Contract violations in turn {i+1}: {snapshot.violations}"
    
    # After all turns, orchestrator should be ready
    assert orchestrator.active_speaker in [None, "user"], "Should be ready for user input after consecutive turns"


@pytest.mark.asyncio
async def test_web_search_turn_with_completion(event_bus, recorder, orchestrator_worker, tts_worker_instance):
    """Test: Web-search turn - acknowledgment + deferred result."""
    orchestrator, llm = orchestrator_worker
    tts = tts_worker_instance
    
    # Patch orchestrator to return SEARCH_WEB intent
    async def mock_route_search(text, **kwargs):
        return Intent(IntentName.SEARCH_WEB, 0.9, {"query": text})
    
    orchestrator.intent_router.route = mock_route_search
    
    await subscribe_recorder(event_bus, recorder)
    
    # Simulate user input that triggers search
    correlation_id = str(uuid.uuid4())
    segment_id = str(uuid.uuid4())
    await event_bus.publish(Event.create(
        EventType.STT_FINAL_TRANSCRIPT,
        {
            "segment_id": segment_id,
            "text": "What is the capital of France?",
            "duration": 2.0,
            "confidence": 0.96
        },
        "stt",
        correlation_id
    ))
    
    # Wait for search to be requested
    action_event = await wait_for_event(recorder, EventType.ACTION_REQUESTED)
    action_correlation_id = action_event.correlation_id
    
    # Simulate search completion
    await event_bus.publish(Event.create(
        EventType.ACTION_COMPLETED,
        {
            "tool_name": "search_web",
            "success": True,
            "output": "Paris is the capital of France.",
        },
        "tool_worker",
        action_correlation_id
    ))
    
    # Get the turn ID
    turn_event = await wait_for_event(recorder, EventType.CONVERSATION_TURN_STARTED)
    turn_id = turn_event.payload.get("turn_id")
    await wait_for_event(recorder, EventType.ASSISTANT_RESPONSE_COMPLETED, turn_id)
    await wait_for_event(recorder, EventType.TTS_STREAM_END, turn_id)
    
    # Validate contract
    snapshot = await validate_turn_contract(turn_id, "web_search", recorder, orchestrator)
    
    assert not snapshot.violations, f"Contract violations: {snapshot.violations}"


@pytest.mark.asyncio
async def test_search_interrupted_before_result(event_bus, recorder, orchestrator_worker, tts_worker_instance):
    """Test: Search turn interrupted before the result arrives."""
    orchestrator, llm = orchestrator_worker
    tts = tts_worker_instance
    
    # Patch orchestrator to return SEARCH_WEB intent
    async def mock_route_search(text, **kwargs):
        return Intent(IntentName.SEARCH_WEB, 0.9, {"query": text})
    
    orchestrator.intent_router.route = mock_route_search
    
    await subscribe_recorder(event_bus, recorder)
    
    # Simulate user input that triggers search
    correlation_id = str(uuid.uuid4())
    segment_id = str(uuid.uuid4())
    await event_bus.publish(Event.create(
        EventType.STT_FINAL_TRANSCRIPT,
        {
            "segment_id": segment_id,
            "text": "Find me a recipe",
            "duration": 1.8,
            "confidence": 0.94
        },
        "stt",
        correlation_id
    ))
    
    await wait_for_event(recorder, EventType.ACTION_REQUESTED)
    
    # User interrupts before search completes
    await event_bus.publish(Event.create(
        EventType.SPEECH_STARTED,
        {"timestamp": time.perf_counter(), "amplitude": 0.8},
        "vad"
    ))
    
    await wait_for_event(recorder, EventType.CONVERSATION_INTERRUPTED)
    
    # Get the turn ID if one was started
    turn_started = await recorder.get_by_type(EventType.CONVERSATION_TURN_STARTED)
    if len(turn_started) > 0:
        turn_id = turn_started[0].payload.get("turn_id")
        
        await wait_for_turn_cleanup(orchestrator, turn_id)
        await event_bus.drain()

        stale_response_events = [
            event
            for event_type in (
                EventType.RESPONSE_READY,
                EventType.ASSISTANT_RESPONSE_PARTIAL,
                EventType.ASSISTANT_RESPONSE_COMPLETED,
            )
            for event in await recorder.get_by_type(event_type)
            if event.payload.get("turn_id") == turn_id
        ]
        assert not stale_response_events, (
            f"Interrupted turn emitted stale response events: {stale_response_events}"
        )


@pytest.mark.asyncio
async def test_personal_memory_turn(event_bus, recorder, orchestrator_worker, tts_worker_instance):
    """Test: Personal-memory turn - answer from memory, router bypassed."""
    orchestrator, llm = orchestrator_worker
    tts = tts_worker_instance
    
    await subscribe_recorder(event_bus, recorder)
    
    # Pre-populate memory context
    orchestrator._latest_memory_context = "- My favorite movie is Inception"
    
    # Override memory request to return our pre-set context
    async def mock_request_memory(query: str) -> str:
        return orchestrator._latest_memory_context
    
    orchestrator._request_memory_context = mock_request_memory
    
    # Simulate personal memory query
    correlation_id = str(uuid.uuid4())
    segment_id = str(uuid.uuid4())
    await event_bus.publish(Event.create(
        EventType.STT_FINAL_TRANSCRIPT,
        {
            "segment_id": segment_id,
            "text": "what is my favorite movie",
            "duration": 2.0,
            "confidence": 0.92
        },
        "stt",
        correlation_id
    ))
    
    turn_event = await wait_for_event(recorder, EventType.CONVERSATION_TURN_STARTED)
    turn_id = turn_event.payload.get("turn_id")
    await wait_for_event(recorder, EventType.ASSISTANT_RESPONSE_COMPLETED, turn_id)
    await wait_for_event(recorder, EventType.TTS_STREAM_END, turn_id)
    
    # Validate contract
    snapshot = await validate_turn_contract(turn_id, "personal_memory", recorder, orchestrator)
    
    assert not snapshot.violations, f"Contract violations: {snapshot.violations}"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
