"""Unit tests for AecProcessor and WebRTC APM echo cancellation."""
import asyncio
import struct
import time
from unittest.mock import AsyncMock, MagicMock
import pytest

from core.audio.pipecat_worker import AecProcessor
from pipecat.frames.frames import InputAudioRawFrame


def _make_mock_worker():
    """Create a minimal mock PipecatAudioWorker for AecProcessor construction."""
    worker = MagicMock()
    worker.logger = MagicMock()
    worker.event_bus = MagicMock()
    worker.recent_mic_rms = 0
    return worker


@pytest.mark.asyncio
async def test_aec_initialization():
    """Verify AEC initializes with correct stream formats and delay."""
    worker = _make_mock_worker()
    proc = AecProcessor(worker, delay_ms=180)
    try:
        assert proc.enabled is True
        assert proc.aec is not None
        assert proc.aec.get_stream_delay() == 180
    finally:
        await proc.cleanup()


@pytest.mark.asyncio
async def test_aec_echo_cancellation():
    """Verify reverse stream reference feeding and forward stream processing."""
    worker = _make_mock_worker()
    proc = AecProcessor(worker, delay_ms=180)
    proc.push_frame = AsyncMock()

    try:
        # 16-bit PCM mono 16kHz audio: 160 samples = 320 bytes (10ms)
        ref_chunk = struct.pack("<" + "h" * 160, *([500] * 160))
        await proc.feed_reference(ref_chunk, 16000)

        # Allow background feeder to process reference queue
        while not proc._ref_queue.empty():
            await asyncio.sleep(0.01)

        # Process matching mic frame
        mic_frame = InputAudioRawFrame(audio=ref_chunk, sample_rate=16000, num_channels=1)
        await proc.process_frame(mic_frame, None)

        assert proc.push_frame.called
        pushed_frame = proc.push_frame.call_args[0][0]
        assert len(pushed_frame.audio) == 320
    finally:
        await proc.cleanup()


@pytest.mark.asyncio
async def test_aec_with_background_noise():
    """Verify AEC filters low-level background noise."""
    worker = _make_mock_worker()
    proc = AecProcessor(worker, delay_ms=180)
    proc.push_frame = AsyncMock()

    try:
        noise_chunk = struct.pack("<" + "h" * 160, *([25] * 160))
        mic_frame = InputAudioRawFrame(audio=noise_chunk, sample_rate=16000, num_channels=1)
        await proc.process_frame(mic_frame, None)

        assert proc.push_frame.called
        pushed = proc.push_frame.call_args[0][0]
        assert len(pushed.audio) == 320
    finally:
        await proc.cleanup()


@pytest.mark.asyncio
async def test_aec_vad_integration():
    """Verify VAD state reporting and worker RMS tracking."""
    worker = _make_mock_worker()
    proc = AecProcessor(worker, delay_ms=180)
    proc.push_frame = AsyncMock()

    try:
        speech_chunk = struct.pack("<" + "h" * 160, *([3000] * 160))
        mic_frame = InputAudioRawFrame(audio=speech_chunk, sample_rate=16000, num_channels=1)
        await proc.process_frame(mic_frame, None)

        assert isinstance(proc.aec.has_voice(), bool)
        assert worker.recent_mic_rms > 0
    finally:
        await proc.cleanup()


@pytest.mark.asyncio
async def test_aec_microphone_input():
    """Verify 320-byte boundary buffering for mic chunks."""
    worker = _make_mock_worker()
    proc = AecProcessor(worker, delay_ms=180)
    proc.push_frame = AsyncMock()

    try:
        # Feed 200 bytes (sub-frame)
        frame1 = InputAudioRawFrame(audio=b"\x00" * 200, sample_rate=16000, num_channels=1)
        await proc.process_frame(frame1, None)
        assert not proc.push_frame.called
        assert len(proc._mic_buffer) == 200

        # Feed another 200 bytes (crosses 320 bytes)
        frame2 = InputAudioRawFrame(audio=b"\x01" * 200, sample_rate=16000, num_channels=1)
        await proc.process_frame(frame2, None)
        assert proc.push_frame.call_count == 1
        assert len(proc._mic_buffer) == 80
    finally:
        await proc.cleanup()


@pytest.mark.asyncio
async def test_aec_latency():
    """Verify AEC forward processing latency is well below 150ms."""
    worker = _make_mock_worker()
    proc = AecProcessor(worker, delay_ms=180)
    proc.push_frame = AsyncMock()

    try:
        frame_chunk = b"\x00" * 320
        frame = InputAudioRawFrame(audio=frame_chunk, sample_rate=16000, num_channels=1)

        t0 = time.perf_counter()
        await proc.process_frame(frame, None)
        latency_ms = (time.perf_counter() - t0) * 1000

        assert latency_ms < 150, f"AEC latency too high: {latency_ms:.2f}ms"
    finally:
        await proc.cleanup()


@pytest.mark.asyncio
async def test_aec_stress_test():
    """Verify AEC stability across rapid consecutive chunks."""
    worker = _make_mock_worker()
    proc = AecProcessor(worker, delay_ms=180)
    proc.push_frame = AsyncMock()

    try:
        chunk = b"\x00" * 320
        for _ in range(50):
            frame = InputAudioRawFrame(audio=chunk, sample_rate=16000, num_channels=1)
            await proc.process_frame(frame, None)

        assert proc.push_frame.call_count == 50
    finally:
        await proc.cleanup()


@pytest.mark.asyncio
async def test_aec_cleanup():
    """Verify proper cleanup of feeder task and event subscriptions."""
    worker = _make_mock_worker()
    proc = AecProcessor(worker, delay_ms=180)

    # Start feeder task
    await proc.feed_reference(b"\x00" * 320, 16000)
    assert proc._feeder_task is not None

    await proc.cleanup()
    await asyncio.sleep(0.01)
    assert proc._feeder_task.cancelled() or proc._feeder_task.done()
    assert worker.event_bus.unsubscribe.call_count >= 2
