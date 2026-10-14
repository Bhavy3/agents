import os
import pyaudio
import numpy as np
import time

def main():
    p = pyaudio.PyAudio()
    target_name = os.getenv("FRIDAY_AUDIO_INPUT_DEVICE", "Microphone Array (Realtek(R) Audio").lower()
    
    device_index = None
    for i in range(p.get_device_count()):
        info = p.get_device_info_by_index(i)
        if target_name in info.get("name", "").lower() and info.get("maxInputChannels") > 0:
            device_index = i
            break
            
    if device_index is None:
        print("Device not found!")
        p.terminate()
        return

    print(f"Using device index: {device_index}")
    
    stream = p.open(format=pyaudio.paInt16,
                    channels=1,
                    rate=16000,
                    input=True,
                    input_device_index=device_index,
                    frames_per_buffer=1024)
                    
    print("Recording for 10 seconds...")
    frames = []
    for _ in range(0, int(16000 / 1024 * 10)):
        data = stream.read(1024, exception_on_overflow=False)
        frames.append(data)
        
    stream.stop_stream()
    stream.close()
    p.terminate()
    
    audio_data = b"".join(frames)
    audio_np = np.frombuffer(audio_data, dtype=np.int16)
    
    rms = np.sqrt(np.mean(audio_np.astype(np.float32)**2))
    peak = np.max(np.abs(audio_np))
    
    print(f"RMS: {rms:.2f}")
    print(f"Peak: {peak}")

if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    main()
