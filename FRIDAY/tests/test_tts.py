import asyncio
import pytest
from unittest.mock import MagicMock, patch

from core.audio.tts import TtsWorker
from core.events.bus import EventBus
from core.events.event_types import EventType
from core.events.models import Event

@pytest.mark.asyncio
async def test_tts_degraded_mode_if_no_model():
    bus = EventBus()
    await bus.start()
    
    # No model path provided
    worker = TtsWorker(bus)
    
    task = asyncio.create_task(worker.run())
    await asyncio.sleep(0.1)
    
    assert worker.voice is None
    assert not worker._is_initialized
    
    await worker.stop()
    await task
    await bus.stop()

@pytest.mark.asyncio
async def test_tts_interruption_flushes_queue():
    bus = EventBus()
    await bus.start()
    
    with patch("core.audio.tts.PiperVoice") as mock_piper_class:
        mock_voice = MagicMock()
        mock_piper_class.load.return_value = mock_voice
        
        # Mock synthesize to return chunks
        def mock_synthesize(text, **kwargs):
            chunk = MagicMock()
            chunk.audio_data = b"fake_audio" * 10000
            return [chunk]
        mock_voice.synthesize.side_effect = mock_synthesize
        
        worker = TtsWorker(bus, model_path="fake.onnx")
        
        # Mock sounddevice to avoid hardware dependency
        with patch("core.audio.tts.sd") as mock_sd:
            mock_stream = mock_sd.RawOutputStream.return_value.__enter__.return_value
            # Make write slow enough that we catch it in the middle
            mock_stream.write.side_effect = lambda data: time.sleep(0.01)
            
            task = asyncio.create_task(worker.run())
            await asyncio.sleep(0.2)
            
            # 1. Send some text (needs a period to trigger sentence segmentation)
            await bus.publish(Event.create(EventType.ASSISTANT_RESPONSE_PARTIAL, {"turn_id": "turn_1", "text": "Hello world."}, "orchestrator"))
            await asyncio.sleep(0.5)
            
            assert worker.chunks_synthesized > 0
            
            # 2. Interrupt
            await bus.publish(Event.create(EventType.SPEECH_STARTED, {"timestamp": 1.0, "amplitude": 0.5}, "vad"))
            await asyncio.sleep(0.2)
            
            assert worker._stop_playback.is_set()
            assert worker._playback_queue.empty()
            assert worker.interruptions >= 1
            
            await worker.stop()
            await task
            await bus.stop()

@pytest.mark.asyncio
async def test_tts_sentence_segmentation():
    bus = EventBus()
    await bus.start()
    
    with patch("core.audio.tts.PiperVoice") as mock_piper_class:
        mock_voice = MagicMock()
        mock_piper_class.load.return_value = mock_voice
        mock_voice.synthesize.return_value = []
        
        worker = TtsWorker(bus, model_path="fake.onnx")
        
        with patch("core.audio.tts.sd"):
            task = asyncio.create_task(worker.run())
            await asyncio.sleep(0.1)
            
            # Send partial text without sentence end
            await bus.publish(Event.create(EventType.ASSISTANT_RESPONSE_PARTIAL, {"turn_id": "turn_1", "text": "Hello"}, "orchestrator"))
            await asyncio.sleep(0.1)
            assert mock_voice.synthesize.call_count == 0
            
            # Send sentence end
            await bus.publish(Event.create(EventType.ASSISTANT_RESPONSE_PARTIAL, {"turn_id": "turn_1", "text": " world!"}, "orchestrator"))
            await asyncio.sleep(0.2)
            assert mock_voice.synthesize.call_count == 1
            
            await worker.stop()
            await task
            await bus.stop()
