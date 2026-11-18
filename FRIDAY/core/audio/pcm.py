"""Small NumPy-based helpers for signed 16-bit PCM audio.

The project uses mono, little-endian PCM16 for its AEC and speech paths.  This
module keeps those operations local so they do not depend on the deprecated
stdlib :mod:`audioop` module (which is removed in Python 3.13).
"""

from dataclasses import dataclass, field

import numpy as np


@dataclass(slots=True)
class PCM16ResamplerState:
    """State needed to continue a PCM16 stream across input chunks."""

    input_rate: int
    output_rate: int
    next_output_index: int = 0
    buffer_start_index: int = 0
    samples: np.ndarray = field(
        default_factory=lambda: np.empty(0, dtype=np.dtype("<i2"))
    )


def pcm16_rms(audio_data: bytes | bytearray | memoryview) -> int:
    """Return the RMS amplitude of little-endian signed 16-bit PCM.

    The integer result matches ``audioop.rms(..., 2)`` for mono PCM: the
    square root is truncated to an integer rather than rounded.
    """

    if len(audio_data) % 2:
        raise ValueError("PCM16 data must contain a whole number of samples")
    samples = np.frombuffer(audio_data, dtype=np.dtype("<i2"))
    if samples.size == 0:
        return 0
    squares = samples.astype(np.int64) * samples.astype(np.int64)
    return int(np.sqrt(np.mean(squares, dtype=np.float64)))


def resample_pcm16(
    audio_data: bytes | bytearray | memoryview,
    input_rate: int,
    output_rate: int,
    state: PCM16ResamplerState | None = None,
) -> tuple[bytes, PCM16ResamplerState]:
    """Resample mono PCM16 with a streaming-safe linear interpolator.

    ``state`` may be passed back into the next call.  The state retains the
    boundary sample needed to interpolate across chunks, so splitting a stream
    into chunks produces the same samples as processing it in one call.  The
    output is clipped to the signed int16 range before serialization.
    """

    if input_rate <= 0 or output_rate <= 0:
        raise ValueError("sample rates must be positive")
    if len(audio_data) % 2:
        raise ValueError("PCM16 data must contain a whole number of samples")

    if state is None:
        state = PCM16ResamplerState(input_rate, output_rate)
    elif (state.input_rate, state.output_rate) != (input_rate, output_rate):
        raise ValueError("resampler state sample rates do not match the input")

    incoming = np.frombuffer(audio_data, dtype=np.dtype("<i2"))
    if state.samples.size:
        samples = np.concatenate((state.samples, incoming))
    else:
        samples = incoming

    start = state.buffer_start_index
    end = start + samples.size - 1
    output: list[int] = []

    while True:
        position_numerator = state.next_output_index * input_rate
        left_index, fraction = divmod(position_numerator, output_rate)
        if fraction == 0:
            if left_index > end:
                break
            value = float(samples[left_index - start])
        else:
            if left_index + 1 > end:
                break
            left = float(samples[left_index - start])
            right = float(samples[left_index + 1 - start])
            value = left + (right - left) * fraction / output_rate

        output.append(int(np.clip(np.rint(value), -32768, 32767)))
        state.next_output_index += 1

    # Retain only samples that can still participate in the next interpolation.
    next_position = state.next_output_index * input_rate
    next_left_index = next_position // output_rate
    trim_count = max(0, next_left_index - start)
    if trim_count:
        samples = samples[trim_count:]
        start += trim_count
    state.buffer_start_index = start
    state.samples = samples.copy()

    return np.asarray(output, dtype=np.dtype("<i2")).tobytes(), state
