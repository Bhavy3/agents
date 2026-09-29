import asyncio
import time
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
        mock_voice.config.sample_rate = 22050
        mock_piper_class.load.return_value = mock_voice
        mock_voice.synthesize.return_value = []
        
        worker = TtsWorker(bus, model_path="fake.onnx")
        # Pre-fill playback queue with chunks to verify interruption flushes them
        for _ in range(10):
            worker._playback_queue.put({"type": "audio", "data": b"fake_audio" * 100, "turn_id": "turn_1"})
            
        task = asyncio.create_task(worker.run())
        await asyncio.sleep(0.01)
        
        # Interrupt
        await bus.publish(Event.create(EventType.SPEECH_STARTED, {"timestamp": 1.0, "amplitude": 0.5}, "vad"))
        await asyncio.sleep(0.1)
        
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
        mock_voice.config.sample_rate = 22050
        mock_piper_class.load.return_value = mock_voice
        mock_voice.synthesize.return_value = []
        
        worker = TtsWorker(bus, model_path="fake.onnx")
        
        task = asyncio.create_task(worker.run())
        await asyncio.sleep(0.1)
        
        mock_voice.synthesize.reset_mock()
        
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

@pytest.mark.asyncio
async def test_tts_stream_end_fired_on_response_completed():
    bus = EventBus()
    await bus.start()
    
    stream_end_events = []
    chunk_events = []
    
    async def on_stream_end(event: Event):
        stream_end_events.append(event)
        
    async def on_chunk(event: Event):
        chunk_events.append(event)
        
    bus.subscribe(EventType.TTS_STREAM_END, on_stream_end)
    bus.subscribe(EventType.TTS_AUDIO_CHUNK, on_chunk)
    
    with patch("core.audio.tts.PiperVoice") as mock_piper_class:
        mock_voice = MagicMock()
        mock_voice.config.sample_rate = 22050
        mock_piper_class.load.return_value = mock_voice
        
        def mock_synthesize(text, **kwargs):
            return [MagicMock(audio_int16_bytes=b"\x01\x00" * 512)]
        mock_voice.synthesize.side_effect = mock_synthesize
        
        worker = TtsWorker(bus, model_path="fake.onnx")
        task = asyncio.create_task(worker.run())
        await asyncio.sleep(0.1)
        
        # Multi-sentence response
        await bus.publish(Event.create(EventType.CONVERSATION_TURN_STARTED, {"turn_id": "turn_123", "speaker": "user"}, "orchestrator"))
        await bus.publish(Event.create(EventType.ASSISTANT_RESPONSE_PARTIAL, {"turn_id": "turn_123", "text": "First sentence. "}, "orchestrator"))
        await bus.publish(Event.create(EventType.ASSISTANT_RESPONSE_PARTIAL, {"turn_id": "turn_123", "text": "Second sentence. "}, "orchestrator"))
        await bus.publish(Event.create(EventType.ASSISTANT_RESPONSE_COMPLETED, {"turn_id": "turn_123", "text": "Done."}, "orchestrator"))
        
        # Wait for publish loop to drain queue
        await asyncio.sleep(0.5)
        
        # Verify chunks arrived and TTS_STREAM_END fired once
        assert len(chunk_events) >= 2
        assert len(stream_end_events) == 1
        assert stream_end_events[0].payload.get("turn_id") == "turn_123"
        
        await worker.stop()
        await task
        await bus.stop()
