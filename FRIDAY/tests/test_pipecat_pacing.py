import pytest
import asyncio
import time
from unittest.mock import Mock, AsyncMock

from core.events.event_types import EventType
from core.events.models import Event
from core.audio.pipecat_worker import TtsOutputProcessor, AecProcessor, PipecatAudioWorker

@pytest.fixture
def mock_worker():
    bus_mock = Mock()
    bus_mock.publish = AsyncMock()
    bus_mock.subscribe = Mock()
    bus_mock.unsubscribe = Mock()
    
    worker = PipecatAudioWorker(bus_mock)
    worker.logger = Mock()
    worker.event_bus = bus_mock
    worker._delayed_unmute = AsyncMock()
    return worker

@pytest.mark.asyncio
async def test_tts_output_processor_duration_tracking_and_scheduling(mock_worker):
    processor = TtsOutputProcessor(mock_worker)
    
    # Start turn
    await processor._handle_turn_started(Event.create(EventType.CONVERSATION_TURN_STARTED, {"turn_id": "turn_1"}, "test"))
    
    # Send a chunk of audio
    sample_rate = 16000
    audio_data = b"\x00" * 32000 # 1 second of 16-bit audio at 16kHz (16000 * 2)
    
    start_time = time.perf_counter()
    await processor._handle_tts_chunk(Event.create(
        EventType.TTS_AUDIO_CHUNK, 
        {"audio_data": audio_data, "sample_rate": sample_rate, "chunk_id": "chunk_1", "turn_id": "turn_1"}, 
        "test"
    ))
    
    assert processor._playback_active is True
    assert processor._current_turn_duration == 1.0
    assert processor._turn_start_time > 0.0
    
    # Send stream end
    await processor._handle_tts_stream_end(Event.create(
        EventType.TTS_STREAM_END,
        {"turn_id": "turn_1"},
        "test"
    ))
    
    # It should schedule completion because time passed < 1.0 second
    assert processor._completion_task is not None
    assert not processor._completion_task.done()
    
    processor._completion_task.cancel()

@pytest.mark.asyncio
async def test_tts_output_processor_cancellation(mock_worker):
    processor = TtsOutputProcessor(mock_worker)
    
    await processor._handle_turn_started(Event.create(EventType.CONVERSATION_TURN_STARTED, {"turn_id": "turn_2"}, "test"))
    
    audio_data = b"\x00" * 320000 # 10 seconds of 16-bit audio
    await processor._handle_tts_chunk(Event.create(
        EventType.TTS_AUDIO_CHUNK, 
        {"audio_data": audio_data, "sample_rate": 16000, "chunk_id": "chunk_1", "turn_id": "turn_2"}, 
        "test"
    ))
    
    await processor._handle_tts_stream_end(Event.create(
        EventType.TTS_STREAM_END,
        {"turn_id": "turn_2"},
        "test"
    ))
    
    assert processor._completion_task is not None
    assert not processor._completion_task.done()
    
    # Now cancel
    await processor._handle_tts_cancelled(Event.create(
        EventType.TTS_PLAYBACK_CANCELLED,
        {"turn_id": "turn_2"},
        "test"
    ))
    
    await asyncio.sleep(0.01) # allow task to cancel
    
    assert processor._completion_task.cancelled() or processor._completion_task.done()
    assert processor._playback_active is False

@pytest.mark.asyncio
async def test_aec_processor_pacing(mock_worker):
    processor = AecProcessor(mock_worker)
    processor.enabled = True
    processor.aec = Mock()
    
    # Feed 2 seconds of audio
    audio_data = b"\x00" * 64000
    await processor.feed_reference(audio_data, 16000)
    
    assert processor._feeder_task is not None
    assert not processor._feeder_task.done()
    assert processor._ref_queue.qsize() == 1
    
    # Wait a bit for it to pull from queue
    await asyncio.sleep(0.05)
    assert processor._ref_queue.empty()
    
    # The task should still be running and sleeping (since it's a 2 second chunk)
    assert not processor._feeder_task.done()
    
    # Cancel it
    await processor._handle_tts_cancelled(Event.create(
        EventType.TTS_PLAYBACK_CANCELLED,
        {"turn_id": "turn_3"},
        "test"
    ))
    
    assert processor._feeder_task is None
    assert len(processor._ref_buffer) == 0
