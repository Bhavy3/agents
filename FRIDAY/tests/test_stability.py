import asyncio
import time
import pytest
from core.events.bus import EventBus
from core.events.event_types import EventType
from core.events.models import Event
from core.audio.vad import VadWorker
from core.orchestrator.conversation import OrchestratorWorker


@pytest.mark.asyncio
async def test_vad_debounce_prevents_early_speech_start():
    """VAD should not emit SPEECH_STARTED until activation_chunks threshold is met."""
    bus = EventBus()
    await bus.start()
    vad = VadWorker(bus, silence_threshold=0.01, activation_chunks=3); vad._ort_session = None
    await vad.start()
    await asyncio.sleep(0.05)

    speech_events = []
    async def on_speech(e): speech_events.append(e)
    bus.subscribe(EventType.SPEECH_STARTED, on_speech)

    # Send only 2 above-threshold chunks (below activation_chunks=3)
    for _ in range(2):
        await bus.publish(Event.create(
            EventType.AUDIO_CHUNK_RECEIVED,
            {"chunk_size": 64, "amplitude": 0.5, "timestamp": time.perf_counter(), "data": b"\x00" * 64},
            "test"
        ))
    await asyncio.sleep(0.15)
    
    assert len(speech_events) == 0, "VAD fired SPEECH_STARTED before activation threshold"

    await vad.stop()
    await bus.stop()


@pytest.mark.asyncio
async def test_vad_debounce_fires_after_threshold():
    """VAD should emit SPEECH_STARTED only after activation_chunks are received."""
    bus = EventBus()
    await bus.start()
    vad = VadWorker(bus, silence_threshold=0.01, activation_chunks=3); vad._ort_session = None
    await vad.start()
    await asyncio.sleep(0.05)

    speech_events = []
    async def on_speech(e): speech_events.append(e)
    bus.subscribe(EventType.SPEECH_STARTED, on_speech)

    # Send 3 above-threshold chunks (meets activation_chunks=3)
    for _ in range(3):
        await bus.publish(Event.create(
            EventType.AUDIO_CHUNK_RECEIVED,
            {"chunk_size": 64, "amplitude": 0.5, "timestamp": time.perf_counter(), "data": b"\x00" * 64},
            "test"
        ))
    await asyncio.sleep(0.2)
    
    assert len(speech_events) == 1, "VAD did not fire SPEECH_STARTED at activation threshold"

    await vad.stop()
    await bus.stop()


@pytest.mark.asyncio
async def test_orchestrator_interrupt_storm_protection():
    """Rapid SPEECH_STARTED events should only trigger one interruption within cooldown window."""
    from core.router.intent_router import IntentRouter
    from core.llm.streaming_worker import StreamingLlmWorker
    from core.llm.ollama_client import OllamaClient
    from core.llm.stream_aggregator import ResponseAggregator

    bus = EventBus()
    await bus.start()
    
    ollama = OllamaClient()
    aggregator = ResponseAggregator(bus)
    streaming = StreamingLlmWorker(bus, ollama, aggregator)
    router = IntentRouter(bus)
    orchestrator = OrchestratorWorker(bus, router, streaming, interrupt_cooldown_seconds=1.0)
    
    # Simulate active assistant turn
    orchestrator.active_speaker = "assistant"
    
    await orchestrator.start()
    await asyncio.sleep(0.05)
    orchestrator.interruptions = 0

    # Fire 5 SPEECH_STARTED events rapidly (within 0.25s, well under 1.0s cooldown)
    for _ in range(5):
        await bus.publish(Event.create(
            EventType.SPEECH_STARTED,
            {"timestamp": time.perf_counter(), "amplitude": 0.8},
            "test"
        ))
        await asyncio.sleep(0.05)

    await asyncio.sleep(0.2)

    # Despite 5 events, only 1 interruption should be counted due to cooldown
    assert orchestrator.interruptions <= 1, f"Expected 1 interrupt, got {orchestrator.interruptions}"

    await orchestrator.stop()
    await bus.stop()
