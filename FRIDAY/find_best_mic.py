import pyaudio
import time
import struct
import math

def get_rms(data):
    if not data: return 0
    count = len(data) // 2
    formats = f"<{count}h"
    shorts = struct.unpack(formats, data)
    sum_squares = sum(s * s for s in shorts)
    return math.sqrt(sum_squares / count) if count > 0 else 0

p = pyaudio.PyAudio()

print("Scanning all audio devices for working 16000 Hz microphones...")
print("Please SPEAK ALOUD constantly while this runs!\n")

for i in range(p.get_device_count()):
    info = p.get_device_info_by_index(i)
    if info['maxInputChannels'] > 0:
        print(f"Testing Index {i}: {info['name']}")
        try:
            stream = p.open(format=pyaudio.paInt16,
                            channels=1,
                            rate=16000,
                            input=True,
                            input_device_index=i,
                            frames_per_buffer=320)
            
            # Record for 1 second (approx 50 chunks of 320 frames)
            frames = []
            for _ in range(50):
                try:
                    data = stream.read(320, exception_on_overflow=False)
                    frames.append(data)
                except Exception as e:
                    break
            
            stream.stop_stream()
            stream.close()
            
            full_data = b''.join(frames)
            if full_data:
                rms = get_rms(full_data)
                max_amp = max(abs(s) for s in struct.unpack(f"<{len(full_data)//2}h", full_data))
                print(f"  -> SUCCESS! Recorded {len(full_data)} bytes. RMS: {rms:.2f}, Max Amp: {max_amp}")
            else:
                print("  -> FAILED: Stream opened but returned no data.")
                
        except Exception as e:
            print(f"  -> FAILED: Could not open at 16000 Hz. Error: {e}")

p.terminate()
print("\nScan complete.")
