import pyaudio
import math
import struct
import time

def play_test_tone(p, device_index):
    try:
        print(f"\n--- Testing OUTPUT Device {device_index} ---")
        info = p.get_device_info_by_index(device_index)
        print(f"Device Name: {info['name']}")
        
        fs = 44100
        duration = 1.0  # seconds
        f = 440.0  # Hz
        
        stream = p.open(format=pyaudio.paFloat32,
                        channels=1,
                        rate=fs,
                        output=True,
                        output_device_index=device_index)
        
        samples = (math.sin(2 * math.pi * k * f / fs) for k in range(int(fs * duration)))
        data = b''.join(struct.pack('f', sample) for sample in samples)
        
        print("Playing tone... did you hear it?")
        stream.write(data)
        
        stream.stop_stream()
        stream.close()
        print("Done.")
    except Exception as e:
        print(f"Failed to test output device {device_index}: {e}")

def record_and_play(p, input_device_index, output_device_index):
    try:
        print(f"\n--- Testing INPUT Device {input_device_index} ---")
        info = p.get_device_info_by_index(input_device_index)
        print(f"Device Name: {info['name']}")
        
        fs = 44100
        duration = 2.5  # seconds
        chunk = 1024
        
        stream_in = p.open(format=pyaudio.paInt16,
                           channels=1,
                           rate=fs,
                           input=True,
                           input_device_index=input_device_index,
                           frames_per_buffer=chunk)
        
        print("Recording for 2.5 seconds... SPEAK NOW!")
        frames = []
        for _ in range(0, int(fs / chunk * duration)):
            data = stream_in.read(chunk, exception_on_overflow=False)
            frames.append(data)
            
        stream_in.stop_stream()
        stream_in.close()
        print("Recording finished. Playing back on output device...")
        
        stream_out = p.open(format=pyaudio.paInt16,
                            channels=1,
                            rate=fs,
                            output=True,
                            output_device_index=output_device_index)
        
        for frame in frames:
            stream_out.write(frame)
            
        stream_out.stop_stream()
        stream_out.close()
        print("Playback finished.")
    except Exception as e:
        print(f"Failed to test input device {input_device_index}: {e}")

if __name__ == "__main__":
    p = pyaudio.PyAudio()
    
    out_candidates = [3, 8, 11]
    in_candidates = [1, 6, 12, 13]
    
    print("Testing Output Candidates...")
    for idx in out_candidates:
        play_test_tone(p, idx)
        time.sleep(1)
        
    print("\nTesting Input Candidates (using first successful output for playback)...")
    for in_idx in in_candidates:
        record_and_play(p, in_idx, out_candidates[0])
        time.sleep(1)
        
    p.terminate()
