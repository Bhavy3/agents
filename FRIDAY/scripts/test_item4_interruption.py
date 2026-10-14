"""Voice Re-Enable Staging Item 4: Long-Answer Interruption Tests.

Executes Test Case A (8s mid-response interruption) and Test Case B (rapid-fire interruption stress test).
Logs all events and stream traces to tests/logs/interruption.log.
"""
import asyncio
import audioop
import os
import sys
import time
from pathlib import Path
import numpy as np

# Ensure root is on path
root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))

from piper.voice import PiperVoice
from silero_vad import load_silero_vad
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams

from core.events.bus import EventBus
from core.events.event_types import EventType
from core.events.models import Event
from core.llm.local_llm_client import LocalLLMClient, create_llm_client
from core.llm.stream_aggregator import ResponseAggregator
from core.llm.streaming_worker import StreamingLlmWorker
from core.orchestrator.conversation import OrchestratorWorker
from core.audio.pipecat_worker import PipecatAudioWorker, TtsOutputProcessor, VAD_CONFIG, AUDIO_INPUT_DEVICE
from core.audio.tts import TtsWorker
from core.router.rules import Intent, IntentName
from core.router.intent_router import IntentRouter
from core.config.settings import load_settings

sys.stdout.reconfigure(encoding="utf-8")


def synthesize_spoken_phrase(voice: PiperVoice, phrase: str) -> np.ndarray:
    """Synthesizes real speech using Piper TTS, resampled to 16kHz float32."""
    raw_pcm_chunks = [chunk.audio_int16_bytes for chunk in voice.synthesize(phrase)]
    raw_pcm = b"".join(raw_pcm_chunks)
    resampled, _ = audioop.ratecv(raw_pcm, 2, 1, 22050, 16000, None)
    audio = np.frombuffer(resampled, dtype=np.int16).astype(np.float32) / 32768.0
    return audio


class Item4IntentRouter(IntentRouter):
    def __init__(self, bus: EventBus, streaming_worker: StreamingLlmWorker, orchestrator: OrchestratorWorker | None = None):
        super().__init__(bus)
        self.streaming_worker = streaming_worker
        self.orchestrator = orchestrator

    async def route(self, text: str, *args, **kwargs) -> Intent:
        # If user asks to stop, confirm stop
        if text.strip().lower() in ["stop", "stop.", "halt"]:
            return Intent(IntentName.CHAT, 1.0, {"response_text": "Stopped."})
        # If weather query, answer weather
        if "weather" in text.lower():
            return Intent(IntentName.CHAT, 1.0, {"response_text": "The weather is currently 72 degrees and sunny with clear skies."})
        # If math query, compute answer
        if "2+2" in text.replace(" ", ""):
            return Intent(IntentName.CHAT, 1.0, {"response_text": "2 + 2 is 4."})
        # Long queries: stream live from llama-server with real-time TTS publishing
        if self.orchestrator:
            self.orchestrator._chat_confirmed = True
        streamed = await self.streaming_worker.stream_reasoning(text, kwargs.get("correlation_id"))
        return Intent(IntentName.CHAT, 1.0, {"response_text": streamed})


async def run_item4_interruption_suite():
    log_dir = root / "tests" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    interruption_log_path = log_dir / "interruption.log"
    log_file = open(interruption_log_path, "w", encoding="utf-8")

    def log_line(msg: str):
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        formatted = f"[{ts}] {msg}"
        print(formatted)
        log_file.write(formatted + "\n")
        log_file.flush()

    log_line("=" * 60)
    log_line("ITEM 4: LONG-ANSWER INTERRUPTION TESTS STARTING")
    log_line("=" * 60)

    settings = load_settings()
    bus = EventBus()
    await bus.start()

    # Event tracking
    events_log = []
    stream_chunks = []
    tts_chunks = []
    active_turn_id = None
    interruption_fired = asyncio.Event()
    tts_stream_end_fired = asyncio.Event()
    turn_ended_fired = asyncio.Event()
    chunks_after_interruption = 0

    async def on_event(event: Event):
        nonlocal active_turn_id, chunks_after_interruption
        events_log.append(event)
        
        if event.event_type == EventType.TTS_AUDIO_CHUNK:
            chunk_id = event.payload.get("chunk_id")
            turn_id = event.payload.get("turn_id")
            tts_chunks.append(chunk_id)
            log_line(f"EVENT: TTS_AUDIO_CHUNK | chunk_id={chunk_id} turn_id={turn_id} bytes={len(event.payload.get('audio_data', b''))}")
            return

        log_line(f"EVENT: {event.event_type.value} | payload={event.payload}")

        if event.event_type == EventType.CONVERSATION_TURN_STARTED:
            active_turn_id = event.payload.get("turn_id")
        elif event.event_type == EventType.STREAM_CHUNK:
            chunk = event.payload.get("chunk", "")
            stream_chunks.append(chunk)
            if interruption_fired.is_set():
                chunks_after_interruption += 1
                log_line(f"⚠ STREAM_CHUNK LEAK DETECTED: {repr(chunk)}")
        elif event.event_type == EventType.CONVERSATION_INTERRUPTED:
            interruption_fired.set()
        elif event.event_type == EventType.TTS_STREAM_END:
            tts_stream_end_fired.set()
        elif event.event_type == EventType.CONVERSATION_TURN_ENDED:
            turn_ended_fired.set()

    for et in EventType:
        bus.subscribe(et, on_event)

    # Workers
    llm_client = LocalLLMClient(
        base_url=settings.ollama_base_url,
        model=settings.ollama_model,
        timeout_seconds=60.0,
        max_retries=settings.ollama_max_retries,
        provider=settings.llm_provider,
        max_tokens=1500,
    )
    aggregator = ResponseAggregator(bus)
    streaming_worker = StreamingLlmWorker(bus, llm_client, aggregator)

    intent_router = Item4IntentRouter(bus, streaming_worker)
    orchestrator = OrchestratorWorker(
        bus,
        intent_router=intent_router,
        streaming_worker=streaming_worker,
        response_timeout_seconds=60.0,
        interrupt_cooldown_seconds=0.5,
    )
    intent_router.orchestrator = orchestrator
    # Prevent model_manager from switching/killing daemon in test
    orchestrator.adaptive_router.model_manager = None

    # Memory stub to avoid 0.5s timeout when MemoryWorker is not running
    async def on_memory_query(e: Event):
        if e.event_type == EventType.MEMORY_QUERY_REQUEST:
            await bus.publish(Event.create(
                EventType.MEMORY_QUERY_RESULT,
                {"results": [], "latency_ms": 1.0},
                "memory_worker",
                e.correlation_id,
            ))
    bus.subscribe(EventType.MEMORY_QUERY_REQUEST, on_memory_query)

    # Avoid artificial thinking delay in test to measure pure LLM TTFT
    async def no_delay(*args, **kwargs):
        pass
    orchestrator.presence.simulate_thinking_delay = no_delay

    tts_model = settings.tts_model_path or "data/models/tts/en_US-lessac-medium.onnx"
    tts_cfg = settings.tts_config_path or "data/models/tts/en_US-lessac-medium.onnx.json"
    tts_worker = TtsWorker(bus, model_path=tts_model, config_path=tts_cfg)
    pipecat_worker = PipecatAudioWorker(bus)
    tts_processor = TtsOutputProcessor(pipecat_worker)
    bus.subscribe(EventType.TTS_PLAYBACK_STARTED, pipecat_worker._handle_tts_started)
    bus.subscribe(EventType.TTS_PLAYBACK_COMPLETED, pipecat_worker._handle_tts_completed)
    bus.subscribe(EventType.TTS_PLAYBACK_CANCELLED, pipecat_worker._handle_tts_cancelled)
    bus.subscribe(EventType.RESPONSE_READY, pipecat_worker._handle_response_ready)

    orchestrator_task = asyncio.create_task(orchestrator.run())
    tts_task = asyncio.create_task(tts_worker.run())
    await asyncio.sleep(0.3)

    voice = PiperVoice.load("data/models/tts/en_US-lessac-medium.onnx")
    vad_model = load_silero_vad()

    # =========================================================================
    # TEST CASE A: Interruption during long generation (mid-response after 8s)
    # =========================================================================
    log_line("\n" + "=" * 60)
    log_line("TEST CASE A: 8s Mid-Response Interruption")
    log_line("Prompt: 'Explain the history of the internet in detail, covering all major milestones.'")
    log_line("=" * 60)

    stream_chunks.clear()
    tts_chunks.clear()
    interruption_fired.clear()
    chunks_after_interruption = 0

    t_start = time.perf_counter()
    await bus.publish(Event.create(
        EventType.USER_TEXT_RECEIVED,
        {"text": "Explain the history of the internet in detail, covering all major milestones from ARPANET through protocols, web browsers, and modern distributed systems."},
        source="test_user"
    ))

    # Wait for first stream chunk to measure TTFT
    log_line("Waiting for response streaming to begin...")
    while not stream_chunks and (time.perf_counter() - t_start) < 10.0:
        await asyncio.sleep(0.05)

    ttft_seconds = time.perf_counter() - t_start
    log_line(f"✓ First chunk received in {ttft_seconds:.3f}s (Target: < 2.0s)")

    # Allow FRIDAY to generate & speak for 8.0 seconds (mid-response during long generation)
    log_line("Allowing generation & speech to proceed for 8.0 seconds...")
    await asyncio.sleep(8.0)

    chunks_at_8s = len(stream_chunks)
    tts_chunks_at_8s = len(tts_chunks)
    is_active = bool(streaming_worker._active_tasks)
    log_line(f"At 8.0s mark: Actively streaming={is_active}, Generated {chunks_at_8s} text chunks, synthesized {tts_chunks_at_8s} audio chunks.")

    # Synthesize user speech: "Never mind, what's the weather?"
    log_line("\nUser speaks interruption: 'Never mind, what\'s the weather?'")
    speech_audio = synthesize_spoken_phrase(voice, "Never mind, what's the weather?")

    # Feed frames to calibrated VAD (start_secs=0.15)
    frame_size = 512
    vad_detected_ms = None
    for i in range(0, len(speech_audio), frame_size):
        frame = speech_audio[i:i + frame_size]
        if len(frame) < frame_size:
            break
        conf = vad_model(frame, 16000)
        if conf > 0.7:
            vad_detected_ms = (i / 16000.0) * 1000.0
            break

    log_line(f"✓ Silero VAD detected speech at {vad_detected_ms:.1f} ms")

    # Fire SPEECH_STARTED
    t_interrupt = time.perf_counter()
    await bus.publish(Event.create(
        EventType.SPEECH_STARTED,
        {"timestamp": time.time(), "amplitude": 0.8},
        source="PipecatAudioWorker"
    ))

    # Wait for CONVERSATION_INTERRUPTED event
    await asyncio.wait_for(interruption_fired.wait(), timeout=2.0)
    interruption_latency_ms = (time.perf_counter() - t_interrupt) * 1000.0
    log_line(f"✓ Orchestrator fired CONVERSATION_INTERRUPTED in {interruption_latency_ms:.2f} ms")

    # Wait 0.5s to verify generation & TTS have ceased
    await asyncio.sleep(0.5)
    log_line(f"Chunks produced after interruption: {chunks_after_interruption}")
    log_line(f"safety_net_fires count: {pipecat_worker.safety_net_fires}")

    # STT delivers transcript of new query: "Never mind, what's the weather?"
    log_line("\nSTT delivers transcript: 'Never mind, what\'s the weather?'")
    weather_answered = asyncio.Event()
    weather_response_text = ""

    async def on_weather_resp(e: Event):
        nonlocal weather_response_text
        if e.event_type == EventType.RESPONSE_READY:
            text = str(e.payload.get("text", "")).lower()
            if "weather" in text or "sunny" in text or "72" in text:
                weather_response_text = e.payload.get("text", "")
                weather_answered.set()

    bus.subscribe(EventType.RESPONSE_READY, on_weather_resp)

    await bus.publish(Event.create(
        EventType.STT_FINAL_TRANSCRIPT,
        {"segment_id": "seg_weather", "text": "Never mind, what's the weather?", "duration": 1.2, "confidence": 0.99},
        source="stt"
    ))

    await asyncio.wait_for(weather_answered.wait(), timeout=10.0)
    log_line(f"✓ FRIDAY responded to new query cleanly: '{weather_response_text}'")

    case_a_passed = (
        ttft_seconds < 2.0
        and vad_detected_ms < 250.0
        and chunks_after_interruption == 0
        and pipecat_worker.safety_net_fires == 0
        and weather_answered.is_set()
    )
    log_line(f"Test Case A Verdict: {'✓ PASS' if case_a_passed else '⚠ FAIL'}")

    # =========================================================================
    # TEST CASE B: Rapid-Fire Interruptions (Stress Test)
    # =========================================================================
    log_line("\n" + "=" * 60)
    log_line("TEST CASE B: Rapid-Fire Interruptions (Stress Test)")
    log_line("User: 'Give me a very long explanation of machine learning algorithms'")
    log_line("[After 3s] User: 'Stop'")
    log_line("[After 1s] User: 'What\'s 2+2?'")
    log_line("=" * 60)

    stream_chunks.clear()
    tts_chunks.clear()
    interruption_fired.clear()
    chunks_after_interruption = 0

    await bus.publish(Event.create(
        EventType.USER_TEXT_RECEIVED,
        {"text": "Give me a very long explanation of machine learning algorithms and neural network architectures in extensive detail"},
        source="test_user"
    ))

    # Wait for chunks to start, then sleep 3s
    while not stream_chunks:
        await asyncio.sleep(0.05)
    log_line("Generation started, waiting 3.0s...")
    await asyncio.sleep(3.0)

    # User interrupts with "Stop"
    log_line("User interrupts: 'Stop'")
    t_interrupt_b = time.perf_counter()
    await bus.publish(Event.create(
        EventType.SPEECH_STARTED,
        {"timestamp": time.time(), "amplitude": 0.9},
        source="PipecatAudioWorker"
    ))
    await asyncio.wait_for(interruption_fired.wait(), timeout=2.0)
    interruption_latency_b = (time.perf_counter() - t_interrupt_b) * 1000.0
    log_line(f"✓ Rapid-fire interruption handled in {interruption_latency_b:.2f} ms")

    await bus.publish(Event.create(
        EventType.STT_FINAL_TRANSCRIPT,
        {"segment_id": "seg_stop", "text": "Stop", "duration": 0.4, "confidence": 0.99},
        source="stt"
    ))

    # Wait 1.0s
    log_line("Pausing 1.0s before new query...")
    await asyncio.sleep(1.0)

    # User asks "What's 2+2?"
    log_line("User asks new query: 'What\'s 2+2?'")
    math_answered = asyncio.Event()
    math_response_text = ""

    async def on_math_resp(e: Event):
        nonlocal math_response_text
        if e.event_type == EventType.RESPONSE_READY and "4" in str(e.payload.get("text", "")):
            math_response_text = e.payload.get("text", "")
            math_answered.set()

    bus.subscribe(EventType.RESPONSE_READY, on_math_resp)

    await bus.publish(Event.create(
        EventType.STT_FINAL_TRANSCRIPT,
        {"segment_id": "seg_math", "text": "What's 2+2?", "duration": 0.8, "confidence": 0.99},
        source="stt"
    ))

    await asyncio.wait_for(math_answered.wait(), timeout=10.0)
    log_line(f"✓ FRIDAY responded to math query accurately: '{math_response_text}'")

    case_b_passed = (
        math_answered.is_set()
        and "4" in math_response_text
        and pipecat_worker.safety_net_fires == 0
        and chunks_after_interruption == 0
    )
    log_line(f"Test Case B Verdict: {'✓ PASS' if case_b_passed else '⚠ FAIL'}")

    # Cleanup
    await orchestrator.stop()
    await tts_worker.stop()
    await tts_processor.cleanup()
    streaming_worker.cancel_all()
    orchestrator_task.cancel()
    tts_task.cancel()
    await bus.stop()
    log_file.close()

    print("\n" + "=" * 60)
    print("ITEM 4 OVERALL VERDICT")
    print("=" * 60)
    print(f"Test Case A (8s Interruption): {'✓ PASS' if case_a_passed else 'FAIL'}")
    print(f"Test Case B (Rapid-Fire):      {'✓ PASS' if case_b_passed else 'FAIL'}")
    print(f"Safety Net Fires:              {pipecat_worker.safety_net_fires} (Target: 0)")
    print(f"Chunk Leakage:                 {chunks_after_interruption} (Target: 0)")
    print("=" * 60)
    return case_a_passed and case_b_passed


if __name__ == "__main__":
    success = asyncio.run(run_item4_interruption_suite())
    sys.exit(0 if success else 1)
