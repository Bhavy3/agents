import asyncio
import numpy as np
import pytest
from unittest.mock import MagicMock, patch

from core.audio.transport import AudioTransportWorker
from core.events.bus import EventBus
from core.events.event_types import EventType


@pytest.fixture
def mock_sd():
    with patch("core.audio.transport.sd") as mock:
        yield mock


@pytest.mark.asyncio
async def test_audio_worker_start_stop(mock_sd):
    bus = EventBus()
    await bus.start()
    
    worker = AudioTransportWorker(bus)
    
    # Start the worker
    started = await worker._start_audio()
    assert started is True
    mock_sd.InputStream.assert_called_once()
    
    # Check that stream started
    stream_mock = mock_sd.InputStream.return_value
    stream_mock.start.assert_called_once()
    
    # Stop the worker
    await worker._stop_audio("test")
    stream_mock.stop.assert_called_once()
    stream_mock.close.assert_called_once()
    
    await bus.drain()
    await bus.stop()


@pytest.mark.asyncio
async def test_audio_worker_buffer_overflow(mock_sd):
    bus = EventBus()
    await bus.start()
    
    # Small buffer for testing overflow
    worker = AudioTransportWorker(bus, max_buffer_chunks=2)
    await worker._start_audio()
    
    # Simulate callbacks — these now go into _chunk_queue, not _buffer
    dummy_data = np.zeros((1024, 1), dtype="float32")
    worker._audio_callback(dummy_data, 1024, None, None)
    worker._audio_callback(dummy_data, 1024, None, None)
    
    # Queue should have 2 items
    assert worker._chunk_queue.qsize() == 2
    
    # Third callback should trigger drop-oldest in queue (max_buffer_chunks*2 = 4 queue slots)
    # but with only 2 buffer chunks the deque will cap at 2
    worker._audio_callback(dummy_data, 1024, None, None)
    worker._audio_callback(dummy_data, 1024, None, None)
    worker._audio_callback(dummy_data, 1024, None, None)  # 5th into a queue of maxsize=4 → drop-oldest
    
    # Manually drain queue into buffer (simulating what work() does)
    import queue
    drained = 0
    while True:
        try:
            chunk_copy, frames, timestamp = worker._chunk_queue.get_nowait()
        except queue.Empty:
            break
        worker._buffer.append(chunk_copy)
        drained += 1
    
    assert len(worker._buffer) == 2  # deque maxlen=2 keeps last 2
    assert drained >= 2  # at least some chunks were drained
    
    await worker._stop_audio()
    await bus.drain()
    await bus.stop()


@pytest.mark.asyncio
async def test_audio_worker_timeout(mock_sd):
    bus = EventBus()
    await bus.start()
    
    worker = AudioTransportWorker(bus, inactivity_timeout_seconds=0.2)
    
    events = []
    bus.subscribe(EventType.AUDIO_STREAM_TIMEOUT, lambda e: events.append(e))
    
    # Start worker and run loop
    task = asyncio.create_task(worker.run())
    
    # Wait for timeout to trigger
    await asyncio.sleep(0.5)
    
    assert len(events) == 1
    assert events[0].payload["timeout_type"] == "inactivity"
    
    await worker.stop()
    await task
    await bus.drain()
    await bus.stop()


@pytest.mark.asyncio
async def test_audio_worker_degraded_mode():
    bus = EventBus()
    await bus.start()
    
    events = []
    bus.subscribe(EventType.AUDIO_DEVICE_ERROR, lambda e: events.append(e))
    
    # Patch sounddevice to None to simulate failure/degraded mode
    with patch("core.audio.transport.sd", None):
        worker = AudioTransportWorker(bus)
        started = await worker._start_audio()
        
        assert started is False
        await asyncio.sleep(0.1)
        assert len(events) == 1
        assert events[0].payload["error"] == "sounddevice library not available"
        
    await bus.drain()
    await bus.stop()
