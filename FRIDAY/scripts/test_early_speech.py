"""Step 4: VAD early-speech preservation test with real speech synthesis."""
import asyncio
import sys
from pathlib import Path
import numpy as np

root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))

from core.audio.pcm import resample_pcm16
from piper.voice import PiperVoice
from silero_vad import load_silero_vad

sys.stdout.reconfigure(encoding="utf-8")


def synthesize_spoken_word(voice: PiperVoice, word: str) -> np.ndarray:
    """Synthesizes real spoken word using Piper, resampled to 16kHz float32."""
    raw_pcm_chunks = [chunk.audio_int16_bytes for chunk in voice.synthesize(word)]
    raw_pcm = b"".join(raw_pcm_chunks)
    # Resample from 22050 to 16000
    resampled, _ = resample_pcm16(raw_pcm, 22050, 16000)
    # Convert int16 to float32
    audio = np.frombuffer(resampled, dtype=np.int16).astype(np.float32) / 32768.0

    # Add 50ms (800 samples) pre-silence
    pre_silence = np.zeros(800, dtype=np.float32)
    return np.concatenate([pre_silence, audio])


async def test_early_speech(start_secs=0.15):
    voice = PiperVoice.load("data/models/tts/en_US-lessac-medium.onnx")
    vad_model = load_silero_vad()

    print(f"Testing early speech cutoff with start_secs={start_secs}")
    utterances = ["yes", "no", "ok", "hi"]
    results = []
    frame_size = 512

    for utterance in utterances:
        audio = synthesize_spoken_word(voice, utterance)
        first_speech_ms = None

        for i in range(0, len(audio), frame_size):
            frame = audio[i:i + frame_size]
            if len(frame) < frame_size:
                break
            conf = vad_model(frame, 16000)
            if conf > 0.5 and first_speech_ms is None:
                # Frame timestamp in ms
                first_speech_ms = (i / 16000.0) * 1000.0

        if first_speech_ms is not None:
            # Latency relative to speech onset at 50ms
            detection_latency = max(0.0, first_speech_ms - 50.0)
            print(f"  '{utterance}': speech detected at {detection_latency:.0f} ms")
            results.append((utterance, detection_latency))
        else:
            print(f"  '{utterance}': NO SPEECH DETECTED ⚠")

    avg_detection_ms = (sum(lat for _, lat in results) / len(results)) if results else 0
    print(f"\nAverage detection latency: {avg_detection_ms:.0f} ms")
    verdict = "✓ OK" if avg_detection_ms < 250 else "⚠ May cut off early speech"
    print(f"Verdict: {verdict}")


if __name__ == "__main__":
    asyncio.run(test_early_speech(start_secs=0.15))
