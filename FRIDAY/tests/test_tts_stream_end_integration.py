import asyncio
import time
from unittest.mock import MagicMock, patch
import pytest

from core.audio.pipecat_worker import PipecatAudioWorker, TtsOutputProcessor
from core.audio.tts import TtsWorker
from core.events.bus import EventBus
from core.events.event_types import EventType
from core.events.models import Event
from core.metrics.metrics import RuntimeMetrics


@pytest.mark.asyncio
async def test_stream_end_completes_playback_without_safety_net():
    bus = EventBus()
    await bus.start()

    worker = PipecatAudioWorker(bus)
    proc = TtsOutputProcessor(worker)

    completed_events = []
    safety_net_events = []

    async def on_completed(event: Event):
        completed_events.append(event)

    bus.subscribe(EventType.TTS_PLAYBACK_COMPLETED, on_completed)

    # 1. Turn started
    turn_id = "turn_test_1"
    await bus.publish(Event.create(EventType.CONVERSATION_TURN_STARTED, {"turn_id": turn_id}, "orchestrator"))

    # 2. Audio chunks arrive
    for i in range(3):
        await bus.publish(Event.create(
            EventType.TTS_AUDIO_CHUNK,
            {"chunk_id": f"c_{i}", "audio_data": b"\x00\x01" * 160, "sample_rate": 22050, "turn_id": turn_id},
            "tts"
        ))

    # 3. Stream end arrives
    await bus.publish(Event.create(EventType.TTS_STREAM_END, {"turn_id": turn_id}, "tts"))

    # Wait briefly for event bus dispatch
    await asyncio.sleep(0.2)

    assert len(completed_events) == 1
    assert completed_events[0].payload.get("turn_id") == turn_id
    assert worker.stream_end_fires == 1
    assert worker.safety_net_fires == 0

    await proc.cleanup()
    await worker.stop()
    await bus.stop()


@pytest.mark.asyncio
async def test_rapid_consecutive_turns_stream_end():
    bus = EventBus()
    await bus.start()

    worker = PipecatAudioWorker(bus)
    proc = TtsOutputProcessor(worker)

    completed_events = []
    async def on_completed(event: Event):
        completed_events.append(event)
    bus.subscribe(EventType.TTS_PLAYBACK_COMPLETED, on_completed)

    # 3 rapid consecutive turns
    for turn_idx in range(3):
        turn_id = f"rapid_turn_{turn_idx}"
        await bus.publish(Event.create(EventType.CONVERSATION_TURN_STARTED, {"turn_id": turn_id}, "orchestrator"))

        for chunk_idx in range(2):
            await bus.publish(Event.create(
                EventType.TTS_AUDIO_CHUNK,
                {"chunk_id": f"{turn_id}_c{chunk_idx}", "audio_data": b"\x00\x02" * 160, "sample_rate": 22050, "turn_id": turn_id},
                "tts"
            ))

        await bus.publish(Event.create(EventType.TTS_STREAM_END, {"turn_id": turn_id}, "tts"))
        await asyncio.sleep(0.05)

    await asyncio.sleep(0.2)

    assert len(completed_events) == 3
    assert worker.stream_end_fires == 3
    assert worker.safety_net_fires == 0

    await proc.cleanup()
    await worker.stop()
    await bus.stop()


@pytest.mark.asyncio
async def test_empty_turn_stream_end_fires_immediately():
    bus = EventBus()
    await bus.start()

    worker = PipecatAudioWorker(bus)
    proc = TtsOutputProcessor(worker)

    completed_events = []
    async def on_completed(event: Event):
        completed_events.append(event)
    bus.subscribe(EventType.TTS_PLAYBACK_COMPLETED, on_completed)

    # Empty turn (e.g. no audio produced)
    turn_id = "empty_turn"
    await bus.publish(Event.create(EventType.CONVERSATION_TURN_STARTED, {"turn_id": turn_id}, "orchestrator"))
    await bus.publish(Event.create(EventType.TTS_STREAM_END, {"turn_id": turn_id}, "tts"))

    await asyncio.sleep(0.1)

    assert len(completed_events) == 1
    assert completed_events[0].payload.get("turn_id") == turn_id
    assert worker.stream_end_fires == 1
    assert worker.safety_net_fires == 0

    await proc.cleanup()
    await worker.stop()
    await bus.stop()


@pytest.mark.asyncio
async def test_cancelled_turn_ignores_stream_end():
    bus = EventBus()
    await bus.start()

    worker = PipecatAudioWorker(bus)
    proc = TtsOutputProcessor(worker)

    completed_events = []
    async def on_completed(event: Event):
        completed_events.append(event)
    bus.subscribe(EventType.TTS_PLAYBACK_COMPLETED, on_completed)

    turn_id = "cancelled_turn"
    await bus.publish(Event.create(EventType.CONVERSATION_TURN_STARTED, {"turn_id": turn_id}, "orchestrator"))
    await bus.publish(Event.create(
        EventType.TTS_AUDIO_CHUNK,
        {"chunk_id": "c1", "audio_data": b"\x00\x01" * 160, "sample_rate": 22050, "turn_id": turn_id},
        "tts"
    ))
    
    # User interrupts / cancels turn
    await bus.publish(Event.create(EventType.CONVERSATION_INTERRUPTED, {"turn_id": turn_id, "reason": "user_interruption"}, "orchestrator"))

    # Stream end arrives late for the cancelled turn
    await bus.publish(Event.create(EventType.TTS_STREAM_END, {"turn_id": turn_id}, "tts"))

    await asyncio.sleep(0.1)

    # Completed should not fire for cancelled turn
    assert len(completed_events) == 0
    assert worker.stream_end_fires == 0
    assert worker.safety_net_fires == 0

    await proc.cleanup()
    await worker.stop()
    await bus.stop()


@pytest.mark.asyncio
async def test_end_to_end_tts_worker_to_pipecat_processor():
    metrics = RuntimeMetrics()
    bus = EventBus(metrics=metrics)
    await bus.start()

    worker = PipecatAudioWorker(bus)
    proc = TtsOutputProcessor(worker)

    tts = TtsWorker(bus, model_path="fake.onnx")
    tts._is_initialized = True
    tts.voice = MagicMock()
    tts.voice.config.sample_rate = 22050

    def mock_synthesize(text, **kwargs):
        for _ in range(2):
            yield MagicMock(audio_int16_bytes=b"\x00\x05" * 400)
    tts.voice.synthesize.side_effect = mock_synthesize

    tts_task = asyncio.create_task(tts.run())
    await asyncio.sleep(0.05)

    completed_events = []
    async def on_completed(event: Event):
        completed_events.append(event)
    bus.subscribe(EventType.TTS_PLAYBACK_COMPLETED, on_completed)

    # Simulate turn
    turn_id = "e2e_turn_1"
    await bus.publish(Event.create(EventType.CONVERSATION_TURN_STARTED, {"turn_id": turn_id, "speaker": "user"}, "orchestrator"))
    await bus.publish(Event.create(EventType.ASSISTANT_RESPONSE_PARTIAL, {"turn_id": turn_id, "text": "This is sentence one. "}, "orchestrator"))
    await bus.publish(Event.create(EventType.ASSISTANT_RESPONSE_COMPLETED, {"turn_id": turn_id, "text": "This is sentence one. Done."}, "orchestrator"))

    # Wait for synthesis and publish loop to finish
    await asyncio.sleep(0.5)

    assert len(completed_events) == 1
    assert completed_events[0].payload.get("turn_id") == turn_id
    assert worker.stream_end_fires == 1
    assert worker.safety_net_fires == 0
    assert metrics.stream_end_fires == 1
    assert metrics.safety_net_fires == 0
    assert metrics.tts_safety_net_ratio == 0.0

    await tts.stop()
    await tts_task
    await proc.cleanup()
    await worker.stop()
    await bus.stop()
