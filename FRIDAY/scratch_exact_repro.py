import asyncio
import logging
import time
from unittest.mock import MagicMock
from core.audio.tts import TtsWorker
from core.audio.pipecat_worker import TtsOutputProcessor, PipecatAudioWorker
from core.events.bus import EventBus
from core.events.event_types import EventType
from core.events.models import Event
from core.logging.logger import configure_logging, get_logger

async def test_repro():
    bus = EventBus()
    await bus.start()

    worker = PipecatAudioWorker(bus)
    proc = TtsOutputProcessor(worker)

    # Wrap methods to see EXACT execution order and state
    orig_handle_chunk = proc._handle_tts_chunk
    orig_handle_end = proc._handle_tts_stream_end

    async def debug_chunk(e):
        print(f"[{time.time():.4f}] [PROCESSOR] chunk received! chunk_id={e.payload.get('chunk_id')}, turn_id={e.payload.get('turn_id')}, playback_active={proc._playback_active}")
        await orig_handle_chunk(e)
        print(f"[{time.time():.4f}] [PROCESSOR] chunk processed! playback_active={proc._playback_active}")

    async def debug_end(e):
        print(f"[{time.time():.4f}] [PROCESSOR] stream_end received! payload={e.payload}, playback_active={proc._playback_active}, active_turn={proc._active_turn_id}")
        await orig_handle_end(e)
        print(f"[{time.time():.4f}] [PROCESSOR] stream_end processed! playback_active={proc._playback_active}")

    bus._subscribers[EventType.TTS_AUDIO_CHUNK] = [debug_chunk]
    bus._subscribers[EventType.TTS_STREAM_END] = [debug_end]

    async def on_playback_completed(e):
        print(f"[{time.time():.4f}] [BUS] TTS_PLAYBACK_COMPLETED received! payload={e.payload}")
    bus.subscribe(EventType.TTS_PLAYBACK_COMPLETED, on_playback_completed)

    tts = TtsWorker(bus, model_path="fake.onnx")
    tts._is_initialized = True
    tts.voice = MagicMock()
    tts.voice.config.sample_rate = 22050

    def fake_synthesize(text):
        print(f"[{time.time():.4f}] [PIPER] Synthesizing text: '{text}'")
        for i in range(3):
            yield MagicMock(audio_int16_bytes=b"\x00\x01" * 1600)
    tts.voice.synthesize.side_effect = fake_synthesize

    tts_task = asyncio.create_task(tts.run())
    await asyncio.sleep(0.05)

    print("\n--- Simulating exact turn a5884094 ---")
    turn_id = "a5884094"
    
    # 1. CONVERSATION_TURN_STARTED
    await bus.publish(Event.create(EventType.CONVERSATION_TURN_STARTED, {"turn_id": turn_id, "speaker": "user"}, "orchestrator"))
    
    # 2. Acknowledgment partial ("Sure. ")
    await bus.publish(Event.create(EventType.ASSISTANT_RESPONSE_PARTIAL, {"turn_id": turn_id, "text": "Sure. "}, "orchestrator"))
    
    # 3. LLM streams text
    await bus.publish(Event.create(EventType.ASSISTANT_RESPONSE_PARTIAL, {"turn_id": turn_id, "text": "I can help with that. "}, "orchestrator"))
    
    # 4. LLM stream completed
    await bus.publish(Event.create(EventType.ASSISTANT_RESPONSE_COMPLETED, {"turn_id": turn_id, "text": "Sure. I can help with that."}, "orchestrator"))

    # Wait 3.5s to see if safety net or stream_end completes
    for _ in range(35):
        await asyncio.sleep(0.1)
        if not proc._playback_active and proc._current_chunk_id:
            break

    await tts.stop()
    await tts_task
    await bus.stop()

if __name__ == "__main__":
    asyncio.run(test_repro())
