import struct

import numpy as np
import pytest

from core.audio.pcm import pcm16_rms, resample_pcm16


def test_pcm16_rms_uses_signed_int16_samples():
    samples = struct.pack("<hhhh", -1000, 1000, -2000, 2000)

    assert pcm16_rms(samples) == 1581
    assert pcm16_rms(b"") == 0


def test_pcm16_rms_rejects_partial_sample():
    with pytest.raises(ValueError, match="whole number of samples"):
        pcm16_rms(b"\x00")


def test_streaming_resample_matches_single_pass():
    source = np.rint(
        12000 * np.sin(np.linspace(0, 8 * np.pi, 22050, endpoint=False))
    ).astype("<i2")
    source_bytes = source.tobytes()

    whole, _ = resample_pcm16(source_bytes, 22050, 16000)
    state = None
    chunks = []
    for chunk in (source_bytes[:2000], source_bytes[2000:10000], source_bytes[10000:]):
        converted, state = resample_pcm16(chunk, 22050, 16000, state)
        chunks.append(converted)

    assert b"".join(chunks) == whole
    assert len(whole) == 16000 * 2


def test_resample_clips_to_pcm16_range():
    source = np.array([-32768, 32767, 32767], dtype="<i2").tobytes()

    converted, _ = resample_pcm16(source, 22050, 16000)

    assert np.max(np.frombuffer(converted, dtype="<i2")) <= 32767
    assert np.min(np.frombuffer(converted, dtype="<i2")) >= -32768
