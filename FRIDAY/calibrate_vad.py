import pyaudio
import time
import numpy as np

def measure_rms(stream, duration_secs, label):
    print(f"\n[CALIBRATION] Starting '{label}' in 2 seconds...")
    time.sleep(2)
    print(f"[{label}] MEASURING FOR {duration_secs} SECONDS. DO IT NOW!")
    
    chunk_size = 320  # 20ms at 16000Hz
    total_chunks = int(duration_secs * 16000 / chunk_size)
    
    max_vol = 0.0
    vols = []
    
    for _ in range(total_chunks):
        data = stream.read(chunk_size, exception_on_overflow=False)
        audio_int16 = np.frombuffer(data, dtype=np.int16)
        audio_float32 = audio_int16.astype(np.float32)
        
        # Raw microphone RMS only. Pipecat's VAD applies its own loudness
        # normalization, so these values must not be copied directly into
        # VADParams.min_volume.
        volume = float(np.sqrt(np.mean(audio_float32**2))) / 32768.0
        vols.append(volume)
        if volume > max_vol:
            max_vol = volume
            
    avg_vol = sum(vols) / len(vols)
    print(f"[{label}] Done! Peak Volume: {max_vol:.5f}, Avg Volume: {avg_vol:.5f}")
    return max_vol, avg_vol

def main():
    p = pyaudio.PyAudio()
    
    # We use index 1 as previously established
    device_index = 1
    
    stream = p.open(format=pyaudio.paInt16,
                    channels=1,
                    rate=16000,
                    input=True,
                    input_device_index=device_index,
                    frames_per_buffer=320)
                    
    print("VAD CALIBRATION TOOL")
    print("====================")
    
    results = {}
    
    try:
        results['silence'] = measure_rms(stream, 5.0, "Absolute Silence (Don't move or type)")
        results['keyboard'] = measure_rms(stream, 5.0, "Keyboard Noise (Type aggressively)")
        results['quiet_speech'] = measure_rms(stream, 5.0, "Quiet Speech (Whisper a sentence)")
        results['normal_speech'] = measure_rms(stream, 5.0, "Normal Speech (Speak naturally)")
        results['loud_speech'] = measure_rms(stream, 5.0, "Loud Speech (Speak loudly)")
        
        print("\n\n=== FINAL CALIBRATION REPORT ===")
        for label, (peak, avg) in results.items():
            print(f"{label.ljust(15)} | Peak: {peak:.5f} | Avg: {avg:.5f}")
            
        print("\nDo not copy these RMS values directly into VADParams.min_volume.")
        print("Use them to compare noise and speech separation, then validate any threshold in FRIDAY itself.")
    finally:
        stream.stop_stream()
        stream.close()
        p.terminate()

if __name__ == "__main__":
    main()
