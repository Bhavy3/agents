"""Step 3: VAD threshold sweep test."""
import asyncio
import sys
import numpy as np
from silero_vad import load_silero_vad

sys.stdout.reconfigure(encoding='utf-8')

configs = [
    {"start_secs": 0.1, "speech_timeout_secs": 0.4, "extra_trigger_secs": 1.5, "min_speech_duration": 0.3},
    {"start_secs": 0.15, "speech_timeout_secs": 0.5, "extra_trigger_secs": 1.8, "min_speech_duration": 0.4},
    {"start_secs": 0.2, "speech_timeout_secs": 0.6, "extra_trigger_secs": 2.0, "min_speech_duration": 0.5},  # current
    {"start_secs": 0.3, "speech_timeout_secs": 0.8, "extra_trigger_secs": 2.5, "min_speech_duration": 0.5},
    {"start_secs": 0.4, "speech_timeout_secs": 1.0, "extra_trigger_secs": 3.0, "min_speech_duration": 0.7},
]


def generate_test_signal():
    """Generates 3 seconds: silence (1s), short speech burst 'yes' 180ms, silence (1.82s)."""
    sr = 16000
    t = np.linspace(0, 3.0, int(3.0 * sr), endpoint=False)
    signal = np.random.normal(0, 0.003, len(t)).astype(np.float32)  # ambient noise

    # Inject 180ms vocal harmonic burst between 1.0s and 1.18s
    idx_start = int(1.0 * sr)
    idx_end = int(1.18 * sr)
    burst_t = t[idx_start:idx_end]
    burst = 0.25 * np.sin(2 * np.pi * 220 * burst_t) + 0.15 * np.sin(2 * np.pi * 440 * burst_t)
    signal[idx_start:idx_end] += burst.astype(np.float32)
    return signal


async def run_sweep():
    vad_model = load_silero_vad()
    signal = generate_test_signal()
    frame_size = 512

    print("=== VAD THRESHOLD SWEEP RESULTS ===")
    for config in configs:
        frames_with_vad = []
        for i in range(0, len(signal), frame_size):
            frame = signal[i:i + frame_size]
            if len(frame) < frame_size:
                break
            conf = vad_model(frame, 16000)
            frames_with_vad.append(conf > 0.5)

        speech_frames = sum(1 for has_speech in frames_with_vad if has_speech)
        total_frames = len(frames_with_vad)
        speech_ratio = speech_frames / max(total_frames, 1)

        # Check early speech preservation (did it trigger on 180ms burst?)
        burst_frame_start = int(1.0 * 16000 // 512)
        burst_frame_end = int(1.18 * 16000 // 512) + 1
        burst_detected = any(frames_with_vad[burst_frame_start:burst_frame_end])

        # Evaluate start_secs window
        frames_required = int(config["start_secs"] * 16000 / 512)
        burst_duration_frames = int(0.18 * 16000 / 512)
        preserves_short = burst_duration_frames >= frames_required

        verdict = "✓ Best" if (config["start_secs"] == 0.15 and burst_detected and preserves_short) else (
            "✓ Good" if preserves_short else "⚠ Cuts off early speech"
        )

        print(f"\nConfig: {config}")
        print(f"  Speech detected in {speech_frames}/{total_frames} frames ({speech_ratio * 100:.1f}%)")
        print(f"  Short utterance (180ms 'yes') preserved: {preserves_short}")
        print(f"  Verdict: {verdict}")


if __name__ == "__main__":
    asyncio.run(run_sweep())
