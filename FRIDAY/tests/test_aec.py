"""Unit tests for AecProcessor buffering logic (no audio hardware required)."""
import asyncio
import struct
import pytest
from unittest.mock import MagicMock, AsyncMock, patch


def _make_mock_worker():
    """Create a minimal mock PipecatAudioWorker for AecProcessor construction."""
    worker = MagicMock()
    worker.logger = MagicMock()
    return worker


def _make_mock_audio_processor():
    """Create a mock AudioProcessor that records calls and returns input unchanged."""
    ap = MagicMock()
    ap.process_stream.side_effect = lambda data: data
    ap.process_reverse_stream.return_value = None
    ap.get_stream_delay.return_value = 180
    ap.has_voice.return_value = False
    return ap


def _build_aec_processor(mock_ap_instance):
    """Build an AecProcessor with a pre-configured mock AudioProcessor injected."""
    from core.audio.pipecat_worker import AecProcessor
    worker = _make_mock_worker()
    proc = AecProcessor(worker, delay_ms=180)
    # Inject mock — AecProcessor.__init__ already called the real AudioProcessor
    # (or None). Override it with our mock for controlled testing.
    proc.aec = mock_ap_instance
    proc.enabled = True
    return proc


# ---------------------------------------------------------------------------
# Test 1: feed_reference buffers partial chunks, only calls process_reverse_stream
#          on exact 320-byte boundaries
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_feed_reference_320_byte_boundary():
    """feed_reference must only call process_reverse_stream on exact 320-byte chunks."""
    mock_ap = _make_mock_audio_processor()
    proc = _build_aec_processor(mock_ap)

    # Feed 200 bytes (less than 320) — should NOT call process_reverse_stream
    await proc.feed_reference(b'\x00' * 200, 16000)
    
    # Wait for feeder task to process queue
    while not proc._ref_queue.empty():
        await asyncio.sleep(0.01)
    
    mock_ap.process_reverse_stream.assert_not_called()
    assert len(proc._ref_buffer) == 200

    # Feed another 200 bytes (total 400) — should call once (320 bytes) and leave 80
    await proc.feed_reference(b'\x01' * 200, 16000)
    
    while not proc._ref_queue.empty():
        await asyncio.sleep(0.01)
        
    assert mock_ap.process_reverse_stream.call_count == 1
    actual_chunk = mock_ap.process_reverse_stream.call_args[0][0]
    assert len(actual_chunk) == 320
    assert len(proc._ref_buffer) == 80
    
    proc._feeder_task.cancel()


# ---------------------------------------------------------------------------
# Test 2: feed_reference leftover bytes carry over correctly across multiple calls
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_feed_reference_leftover_carryover():
    """Leftover bytes from one feed_reference call must carry into the next."""
    mock_ap = _make_mock_audio_processor()
    proc = _build_aec_processor(mock_ap)

    async def wait_queue():
        while not proc._ref_queue.empty():
            await asyncio.sleep(0.01)

    # Feed exactly 319 bytes — 1 byte short, no call
    await proc.feed_reference(b'\xAA' * 319, 16000)
    await wait_queue()
    mock_ap.process_reverse_stream.assert_not_called()
    assert len(proc._ref_buffer) == 319

    # Feed 1 more byte — total 320, exactly one call
    await proc.feed_reference(b'\xBB' * 1, 16000)
    await wait_queue()
    assert mock_ap.process_reverse_stream.call_count == 1
    assert len(proc._ref_buffer) == 0

    # Feed 640 bytes — exactly two calls, zero leftover
    await proc.feed_reference(b'\xCC' * 640, 16000)
    await wait_queue()
    assert mock_ap.process_reverse_stream.call_count == 3  # 1 + 2
    assert len(proc._ref_buffer) == 0

    # Feed 321 bytes — one call, 1 byte leftover
    await proc.feed_reference(b'\xDD' * 321, 16000)
    await wait_queue()
    assert mock_ap.process_reverse_stream.call_count == 4
    assert len(proc._ref_buffer) == 1

    # Verify no bytes were dropped or duplicated
    total_fed = 319 + 1 + 640 + 321  # 1281
    total_processed = 4 * 320  # 1280
    assert total_fed - total_processed == len(proc._ref_buffer)  # 1
    proc._feeder_task.cancel()


# ---------------------------------------------------------------------------
# Test 3: process_frame mic-side buffering at 320-byte boundaries
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_process_frame_mic_buffering():
    """process_frame must buffer mic audio and call process_stream on 320-byte chunks."""
    mock_ap = _make_mock_audio_processor()
    proc = _build_aec_processor(mock_ap)
    proc.push_frame = AsyncMock()

    # Create a mock frame with 200 bytes (less than 320)
    frame = MagicMock()
    type(frame).__name__ = 'InputAudioRawFrame'
    frame.audio = b'\x00' * 200

    await proc.process_frame(frame, MagicMock())
    mock_ap.process_stream.assert_not_called()
    assert len(proc._mic_buffer) == 200

    # Feed another 200 bytes (total 400) — should call once, leave 80
    frame2 = MagicMock()
    type(frame2).__name__ = 'InputAudioRawFrame'
    frame2.audio = b'\x01' * 200

    await proc.process_frame(frame2, MagicMock())
    assert mock_ap.process_stream.call_count == 1
    actual_chunk = mock_ap.process_stream.call_args[0][0]
    assert len(actual_chunk) == 320
    assert len(proc._mic_buffer) == 80

    # The output frame should have exactly 320 bytes of clean audio
    assert proc.push_frame.call_count == 1
    pushed_frame = proc.push_frame.call_args[0][0]
    assert len(pushed_frame.audio) == 320


# ---------------------------------------------------------------------------
# Test 4: Graceful degradation when AudioProcessor is None
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_aec_degraded_mode_passthrough():
    """When AudioProcessor import fails, AecProcessor must pass frames through unchanged."""
    from core.audio.pipecat_worker import AecProcessor

    worker = _make_mock_worker()
    proc = AecProcessor(worker, delay_ms=180)
    # Force disabled mode (simulates AudioProcessor = None at import time)
    proc.aec = None
    proc.enabled = False

    # feed_reference should be a no-op
    await proc.feed_reference(b'\x00' * 640, 16000)
    # No crash, no calls

    # process_frame should pass the frame through unchanged
    proc.push_frame = AsyncMock()

    frame = MagicMock()
    type(frame).__name__ = 'InputAudioRawFrame'
    frame.audio = b'\xFF' * 500

    direction = MagicMock()
    await proc.process_frame(frame, direction)

    # Frame should be pushed through unchanged
    assert proc.push_frame.call_count == 1
    pushed_frame = proc.push_frame.call_args[0][0]
    # The SAME frame object should be passed through, not reconstructed
    assert pushed_frame is frame


# ---------------------------------------------------------------------------
# Test 5: feed_reference resamples non-16kHz audio before buffering
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_feed_reference_resamples_non_16khz():
    """feed_reference must resample 22050Hz audio to 16000Hz before buffering."""
    mock_ap = _make_mock_audio_processor()
    proc = _build_aec_processor(mock_ap)

    # Feed 22050Hz audio — 1102 bytes = 551 samples at 22050Hz mono 16-bit
    # Generate valid 16-bit PCM silence (not arbitrary bytes)
    input_22k = struct.pack('<' + 'h' * 551, *([0] * 551))  # 1102 bytes
    await proc.feed_reference(input_22k, 22050)

    while not proc._ref_queue.empty():
        await asyncio.sleep(0.01)

    # After resampling 22050->16000, output length should be ~800 bytes
    # What matters: process_reverse_stream was called with 320-byte chunks only
    if mock_ap.process_reverse_stream.call_count > 0:
        for c in mock_ap.process_reverse_stream.call_args_list:
            assert len(c[0][0]) == 320, f"Chunk size was {len(c[0][0])}, expected 320"

    # ratecv state should now be non-None (tracking fractional alignment)
    assert proc._ratecv_state is not None
    
    proc._feeder_task.cancel()
