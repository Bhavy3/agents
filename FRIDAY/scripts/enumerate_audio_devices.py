import sounddevice as sd

devices = sd.query_devices()
for i, dev in enumerate(devices):
    print(f"{i}: {dev['name']} | channels={dev['max_input_channels']} | rate={dev['default_samplerate']} Hz")
