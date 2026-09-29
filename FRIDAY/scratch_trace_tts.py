import asyncio
import time
from unittest.mock import MagicMock
from core.audio.tts import TtsWorker
from core.audio.pipecat_worker import TtsOutputProcessor
from core.events.bus import EventBus
from core.events.event_types import EventType
from core.events.models import Event

async def main():
    bus = EventBus()
    await bus.start()

    events_fired = []
    async def track_event(e):
        events_fired.append((time.time(), e.event_type.value, e.payload))
        print(f"[BUS EVENT] {e.event_type.value} -> {e.payload}")

    for et in [EventType.TTS_PLAYBACK_STARTED, EventType.TTS_PLAYBACK_COMPLETED, EventType.TTS_STREAM_END]:
        bus.subscribe(et, track_event)

    class MockWorker:
        def __init__(self, bus):
            self.event_bus = bus
            self.logger = MagicMock()
            self.mute_gate_delay = 0.6
            self.last_spoken_text = ""
            self.last_spoken_time = 0.0

    mock_worker = MockWorker(bus)
    tts_processor = TtsOutputProcessor(mock_worker)

    orig_stream_end = tts_processor._handle_tts_stream_end
    async def debug_stream_end(event):
        print(f"[PROCESSOR] _handle_tts_stream_end called! playback_active={tts_processor._playback_active}, payload={event.payload}")
        await orig_stream_end(event)
    tts_processor._handle_tts_stream_end = debug_stream_end
    bus._subscribers[EventType.TTS_STREAM_END] = [debug_stream_end, track_event]

    orig_chunk = tts_processor._handle_tts_chunk
    async def debug_chunk(event):
        print(f"[PROCESSOR] _handle_tts_chunk called! chunk_id={event.payload.get('chunk_id')}")
        await orig_chunk(event)
    tts_processor._handle_tts_chunk = debug_chunk
    bus._subscribers[EventType.TTS_AUDIO_CHUNK] = [debug_chunk]

    tts_worker = TtsWorker(bus, model_path="dummy.onnx")
    tts_worker._is_initialized = True
    tts_worker.voice = MagicMock()
    tts_worker.voice.config.sample_rate = 22050
    
    def fake_synthesize(text):
        print(f"[Piper] Synthesizing: {text}")
        for i in range(2):
            time.sleep(0.05)
            yield MagicMock(audio_int16_bytes=b"\x00\x01" * 1600)
    
    tts_worker.voice.synthesize.side_effect = fake_synthesize

    tts_task = asyncio.create_task(tts_worker.run())
    await asyncio.sleep(0.05)

    print("\n--- Starting Turn turn_1 ---")
    await bus.publish(Event.create(EventType.CONVERSATION_TURN_STARTED, {"turn_id": "turn_1", "speaker": "user"}, "orchestrator"))
    await bus.publish(Event.create(EventType.ASSISTANT_RESPONSE_PARTIAL, {"turn_id": "turn_1", "text": "Hello there world. "}, "orchestrator"))
    await bus.publish(Event.create(EventType.ASSISTANT_RESPONSE_COMPLETED, {"turn_id": "turn_1", "text": "Hello there world. Done."}, "orchestrator"))

    await asyncio.sleep(1.0)

    print("\n--- Events recorded: ---")
    for t, name, p in events_fired:
        print(f"  {name}: {p}")

    await tts_worker.stop()
    await tts_task
    await bus.stop()

if __name__ == "__main__":
    asyncio.run(main())
