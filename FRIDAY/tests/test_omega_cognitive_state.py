import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.cognition.cognitive_state import CognitiveStateEngine, TurnState
from core.cognition.cognitive_worker import CognitiveWorker
from core.events.bus import EventBus
from core.events.event_types import EventType
from core.events.models import Event
from core.orchestrator.conversation import OrchestratorWorker


@pytest.mark.asyncio
async def test_cognition_and_orchestrator_share_injected_engine() -> None:
    bus = EventBus()
    engine = CognitiveStateEngine(bus)
    cognition = CognitiveWorker(bus, engine)
    orchestrator = OrchestratorWorker(bus, AsyncMock(), AsyncMock(), cognitive_state=engine)

    assert cognition.state_engine is engine
    assert orchestrator.cognitive_state is engine
    assert orchestrator.state_engine is engine


@pytest.mark.asyncio
async def test_canonical_lifecycle_keeps_interruptions_consistent() -> None:
    bus = EventBus()
    await bus.start()
    engine = CognitiveStateEngine(bus)
    cognition = CognitiveWorker(bus, engine)
    streaming_worker = MagicMock()
    streaming_worker.cancel_all = MagicMock()
    orchestrator = OrchestratorWorker(
        bus,
        AsyncMock(),
        streaming_worker,
        cognitive_state=engine,
    )
    await cognition.start()
    await orchestrator.start()
    await asyncio.sleep(0.05)

    await bus.publish(
        Event.create(
            EventType.SPEECH_STARTED,
            {"timestamp": 1.0, "amplitude": 0.5},
            "PipecatAudioWorker",
        )
    )
    await bus.drain()
    state = await engine.get_state()
    assert state.active_speaker == "user"
    assert state.listening is True
    assert state.speaking is False
    assert orchestrator.active_speaker == "user"

    turn_started = Event.create(
        EventType.CONVERSATION_TURN_STARTED,
        {"turn_id": "turn-1", "speaker": "user"},
        "orchestrator",
    )
    await bus.publish(turn_started)
    await bus.drain()
    state = await engine.get_state()
    assert state.active_turn_id == "turn-1"
    assert state.turn_state == TurnState.THINKING
    assert not (state.speaking and state.listening)

    correlation_id = "corr-1"
    orchestrator._turn_ids_by_correlation_id[correlation_id] = "turn-1"
    orchestrator.active_turn_id = "turn-1"
    orchestrator.active_speaker = "assistant"
    await orchestrator._handle_stream_started(
        Event.create(
            EventType.STREAM_STARTED,
            {"stream_id": "stream-1", "model": "test"},
            "streaming",
            correlation_id,
        )
    )
    await bus.drain()
    state = await engine.get_state()
    assert state.active_speaker == "assistant"
    assert state.speaking is True
    assert state.listening is False

    await orchestrator._handle_stream_completed(
        Event.create(
            EventType.STREAM_COMPLETED,
            {
                "stream_id": "stream-1",
                "full_text": "done",
                "chunk_count": 1,
                "duration": 0.1,
                "cancelled": False,
                "timed_out": False,
                "degraded_mode": False,
            },
            "streaming",
            correlation_id,
        )
    )
    await bus.drain()
    state = await engine.get_state()
    assert state.active_speaker is None
    assert state.speaking is False
    assert state.listening is False

    await bus.publish(
        Event.create(
            EventType.CONVERSATION_TURN_STARTED,
            {"turn_id": "turn-2", "speaker": "user"},
            "orchestrator",
        )
    )
    await bus.drain()
    correlation_id = "corr-2"
    orchestrator._turn_ids_by_correlation_id[correlation_id] = "turn-2"
    orchestrator.active_turn_id = "turn-2"
    orchestrator.active_speaker = "assistant"
    await orchestrator._handle_stream_started(
        Event.create(
            EventType.STREAM_STARTED,
            {"stream_id": "stream-2", "model": "test"},
            "streaming",
            correlation_id,
        )
    )
    await bus.drain()
    await orchestrator._handle_stream_cancelled(
        Event.create(
            EventType.STREAM_CANCELLED,
            {"stream_id": "stream-2", "reason": "test"},
            "streaming",
            correlation_id,
        )
    )
    await bus.drain()
    state = await engine.get_state()
    assert state.active_speaker is None
    assert state.speaking is False
    assert state.listening is False

    await bus.publish(
        Event.create(
            EventType.CONVERSATION_TURN_STARTED,
            {"turn_id": "turn-3", "speaker": "user"},
            "orchestrator",
        )
    )
    await bus.drain()
    correlation_id = "corr-3"
    orchestrator._turn_ids_by_correlation_id[correlation_id] = "turn-3"
    orchestrator.active_turn_id = "turn-3"
    orchestrator.active_speaker = "assistant"
    await orchestrator._handle_stream_started(
        Event.create(
            EventType.STREAM_STARTED,
            {"stream_id": "stream-3", "model": "test"},
            "streaming",
            correlation_id,
        )
    )
    await bus.drain()

    # A live interruption owns the state immediately; a late cancellation for
    # the old turn must not clear the replacement user state.
    await bus.publish(
        Event.create(
            EventType.SPEECH_STARTED,
            {"timestamp": 2.0, "amplitude": 0.8},
            "PipecatAudioWorker",
        )
    )
    await bus.drain()
    state = await engine.get_state()
    assert state.active_speaker == "user"
    assert state.listening is True
    assert state.speaking is False
    assert not (state.speaking and state.listening)

    await bus.publish(
        Event.create(
            EventType.ASSISTANT_RESPONSE_CANCELLED,
            {"turn_id": "turn-1", "reason": "user_interruption"},
            "orchestrator",
        )
    )
    await bus.drain()
    state = await engine.get_state()
    assert state.active_speaker == "user"
    assert state.listening is True
    assert state.speaking is False

    await cognition.stop()
    await orchestrator.stop()
    await bus.stop()


@pytest.mark.asyncio
async def test_live_presence_readiness_is_cancelled_by_interruption() -> None:
    bus = EventBus()
    await bus.start()
    engine = CognitiveStateEngine(bus)
    router = AsyncMock()
    router.route.return_value = None
    streaming_worker = MagicMock()
    streaming_worker.cancel_all = MagicMock()
    orchestrator = OrchestratorWorker(
        bus,
        router,
        streaming_worker,
        cognitive_state=engine,
    )
    orchestrator.presence_timing.update_profile("confused")
    task = asyncio.create_task(orchestrator.run())
    await asyncio.sleep(0.05)

    await bus.publish(
        Event.create(
            EventType.STT_FINAL_TRANSCRIPT,
            {"segment_id": "seg-1", "text": "first turn", "duration": 1.0, "confidence": 1.0},
            "stt",
        )
    )
    await bus.drain()
    for _ in range(100):
        if orchestrator.response_gate.has_pending(orchestrator.active_turn_id):
            break
        await asyncio.sleep(0.01)
    old_turn_id = orchestrator.active_turn_id
    assert old_turn_id is not None
    assert orchestrator.response_gate.has_pending(old_turn_id)

    await bus.publish(
        Event.create(
            EventType.SPEECH_STARTED,
            {"timestamp": 2.0, "amplitude": 0.8},
            "vad",
        )
    )
    await bus.drain()
    await asyncio.sleep(0.05)

    state = await engine.get_state()
    assert state.active_speaker == "user"
    assert state.listening is True
    assert not orchestrator.response_gate.has_pending(old_turn_id)
    assert streaming_worker.cancel_all.called

    await orchestrator.stop()
    await task
    await bus.stop()
