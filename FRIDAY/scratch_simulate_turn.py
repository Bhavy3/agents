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

    class MockWorker:
        def __init__(self, bus):
            self.event_bus = bus
            self.logger = MagicMock()
            self.mute_gate_delay = 0.6
            self.last_spoken_text = ""
            self.last_spoken_time = 0.0

    mock_worker = MockWorker(bus)
    tts_processor = TtsOutputProcessor(mock_worker)

    tts_worker = TtsWorker(bus, model_path="dummy.onnx")
    tts_worker._is_initialized = True
    tts_worker.voice = MagicMock()
    tts_worker.voice.config.sample_rate = 22050
    
    def fake_synthesize(text):
        print(f"[Piper] Synthesizing: '{text}'")
        # Yield 2 chunks
        for i in range(2):
            yield MagicMock(audio_int16_bytes=b"\x00\x01" * 1600)
    
    tts_worker.voice.synthesize.side_effect = fake_synthesize

    tts_task = asyncio.create_task(tts_worker.run())
    await asyncio.sleep(0.05)

    print("\n--- Starting Turn turn_1 ---")
    await bus.publish(Event.create(EventType.CONVERSATION_TURN_STARTED, {"turn_id": "turn_1", "speaker": "user"}, "orchestrator"))
    await bus.publish(Event.create(EventType.ASSISTANT_RESPONSE_PARTIAL, {"turn_id": "turn_1", "text": "Hello there world. "}, "orchestrator"))
    await bus.publish(Event.create(EventType.ASSISTANT_RESPONSE_COMPLETED, {"turn_id": "turn_1", "text": "Hello there world. Done."}, "orchestrator"))

    # Track what tts_processor does
    for _ in range(30):
        await asyncio.sleep(0.1)
        print(f"t={time.time():.2f} playback_active={tts_processor._playback_active} last_chunk={tts_processor._last_chunk_time:.2f}")
        if not tts_processor._playback_active and tts_processor._current_chunk_id:
            print("Playback completed!")
            break

    await tts_worker.stop()
    await tts_task
    await bus.stop()

if __name__ == "__main__":
    asyncio.run(main())
