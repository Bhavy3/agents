import asyncio
import time
import pytest
from unittest.mock import patch, MagicMock

from core.audio.stt import SttWorker
from core.events.bus import EventBus
from core.events.event_types import EventType
from core.events.models import Event

class MockWhisperSegment:
    def __init__(self, text: str):
        self.text = text

class MockWhisperModel:
    def __init__(self, *args, **kwargs):
        self.transcribe_delay = 0.0
        self.crash_on_transcribe = False
        self.segments_to_return = [MockWhisperSegment("hello"), MockWhisperSegment("world")]

    def transcribe(self, audio, **kwargs):
        if self.crash_on_transcribe:
            raise RuntimeError("mock_crash")
        if self.transcribe_delay > 0:
            time.sleep(self.transcribe_delay)
        return self.segments_to_return, None


@pytest.fixture
def mock_whisper():
    with patch("core.audio.stt.WhisperModel", MockWhisperModel):
        yield


@pytest.mark.asyncio
async def test_stt_inference_success(mock_whisper):
    bus = EventBus()
    await bus.start()
    
    worker = SttWorker(bus)
    
    events = []
    async def track(e):
        events.append(e)
        
    bus.subscribe(EventType.STT_PARTIAL_TRANSCRIPT, track)
    bus.subscribe(EventType.STT_FINAL_TRANSCRIPT, track)
    
    task = asyncio.create_task(worker.run())
    
    # Wait for initialization
    await asyncio.sleep(0.1)
    
    # Publish segment
    await bus.publish(
        Event.create(
            EventType.SPEECH_SEGMENT_READY,
            {"segment_id": "seg_1", "audio_data": b"1234" * 10, "duration": 2.0, "chunk_count": 5},
            "test"
        )
    )
    
    await asyncio.sleep(0.2)
    await bus.drain()
    
    # We expect 2 partials ("hello" and "hello world") and 1 final ("hello world")
    assert len(events) == 3
    assert events[0].event_type == EventType.STT_PARTIAL_TRANSCRIPT
    assert events[0].payload["text"] == "hello"
    
    assert events[1].event_type == EventType.STT_PARTIAL_TRANSCRIPT
    assert events[1].payload["text"] == "hello world"
    
    assert events[2].event_type == EventType.STT_FINAL_TRANSCRIPT
    assert events[2].payload["text"] == "hello world"
    assert events[2].payload["segment_id"] == "seg_1"
    
    await worker.stop()
    await task
    await bus.stop()


@pytest.mark.asyncio
async def test_stt_queue_dropping(mock_whisper):
    bus = EventBus()
    await bus.start()
    
    worker = SttWorker(bus, max_queue_size=1)
    
    dropped_events = []
    async def track_drops(e):
        dropped_events.append(e)
        
    bus.subscribe(EventType.STT_SEGMENT_DROPPED, track_drops)
    
    task = asyncio.create_task(worker.run())
    await asyncio.sleep(0.1)
    # Mock model to be slow so queue fills
    worker.model.transcribe_delay = 0.5
    
    # Publish 3 segments quickly
    for i in range(3):
        await bus.publish(
            Event.create(
                EventType.SPEECH_SEGMENT_READY,
                {"segment_id": f"seg_{i}", "audio_data": b"1234" * 10, "duration": 2.0, "chunk_count": 5},
                "test"
            )
        )
        
    await asyncio.sleep(0.1)
    await bus.drain()
    
    # 1 is being processed, 1 is in queue, 1 should be dropped
    assert len(dropped_events) >= 1
    assert dropped_events[0].payload["reason"] == "queue_full"
    
    await worker.stop()
    await task
    await bus.stop()


@pytest.mark.asyncio
async def test_stt_degraded_mode():
    bus = EventBus()
    await bus.start()
    
    # Patch WhisperModel to None to simulate missing library
    with patch("core.audio.stt.WhisperModel", None):
        worker = SttWorker(bus)
        
        errors = []
        async def track_error(e):
            errors.append(e)
            
        bus.subscribe(EventType.STT_MODEL_ERROR, track_error)
        
        task = asyncio.create_task(worker.run())
        await asyncio.sleep(0.1)
        
        assert len(errors) == 1
        assert "faster-whisper not installed" in errors[0].payload["error"]
        
        await worker.stop()
        await task
    await bus.stop()


@pytest.mark.asyncio
async def test_stt_model_error(mock_whisper):
    bus = EventBus()
    await bus.start()
    
    worker = SttWorker(bus)
    
    errors = []
    async def track_error(e):
        errors.append(e)
        
    bus.subscribe(EventType.STT_MODEL_ERROR, track_error)
    
    task = asyncio.create_task(worker.run())
    await asyncio.sleep(0.1)
    worker.model.crash_on_transcribe = True
    
    await bus.publish(
        Event.create(
            EventType.SPEECH_SEGMENT_READY,
            {"segment_id": "seg_crash", "audio_data": b"1234" * 10, "duration": 2.0, "chunk_count": 5},
            "test"
        )
    )
    
    await asyncio.sleep(0.2)
    await bus.drain()
    
    assert len(errors) == 1
    assert errors[0].payload["error"] == "mock_crash"
    
    await worker.stop()
    await task
    await bus.stop()
