import sounddevice as sd
import numpy as np

def test_mic(device_index=1, duration=3, samplerate=16000):
    print(f"Testing mic at index {device_index} for {duration}s...")
    audio = sd.rec(int(duration * samplerate), samplerate=samplerate, channels=1, device=device_index)
    sd.wait()
    
    rms = float(np.sqrt(np.mean(audio ** 2)))
    peak = float(np.max(np.abs(audio)))
    
    print(f"RMS level: {rms:.4f} | Peak: {peak:.4f}")
    verdict = 'GOOD' if rms > 0.005 and peak < 0.9 else 'CHECK LEVELS'
    print(f"Recommendation: {verdict}")
    return rms, peak

if __name__ == "__main__":
    test_mic(1)
