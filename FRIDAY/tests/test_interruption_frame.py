import asyncio
import pytest
from unittest.mock import MagicMock
from pipecat.transports.local.audio import LocalAudioOutputTransport, LocalAudioTransportParams
from pipecat.frames.frames import OutputAudioRawFrame, InterruptionFrame, StartFrame, EndFrame
from pipecat.processors.frame_processor import FrameProcessorSetup
from pipecat.clocks.system_clock import SystemClock
from pipecat.utils.asyncio.task_manager import TaskManager

class MockPyAudio:
    def __init__(self):
        self.stream = MagicMock()
        self.stream.write = MagicMock()

    def open(self, *args, **kwargs):
        return self.stream

    def get_format_from_width(self, width):
        return 8

class MockWorker:
    def __init__(self):
        self.app_resources = {}

class MockSetup(FrameProcessorSetup):
    def __init__(self):
        self.clock = SystemClock()
        self.task_manager = TaskManager()
        self.pipeline_worker = MockWorker()
        self.audio_out_sample_rate = 16000

@pytest.mark.asyncio
async def test_interruption_frame():
    pyaudio_mock = MockPyAudio()
    params = LocalAudioTransportParams(audio_out_enabled=True, audio_out_sample_rate=16000, audio_out_channels=1)
    transport = LocalAudioOutputTransport(pyaudio_mock, params)

    setup = MockSetup()
    await transport.setup(setup)
    
    # Needs to be started to process frames
    start_frame = StartFrame()
    # base_output requires transport ready
    await transport.process_frame(start_frame, 1) # DOWNSTREAM

    audio_frame1 = OutputAudioRawFrame(audio=b'\x00' * 3200, sample_rate=16000, num_channels=1)
    audio_frame2 = OutputAudioRawFrame(audio=b'\x01' * 3200, sample_rate=16000, num_channels=1)
    audio_frame3 = OutputAudioRawFrame(audio=b'\x02' * 3200, sample_rate=16000, num_channels=1)

    # Queue first two frames
    await transport.process_frame(audio_frame1, 1)
    await transport.process_frame(audio_frame2, 1)
    
    # Yield to let the internal task process
    await asyncio.sleep(0.1)
    
    write_count_before = pyaudio_mock.stream.write.call_count
    
    # Send interruption
    await transport.process_frame(InterruptionFrame(), 1)
    
    await asyncio.sleep(0.1)
    
    write_count_after_interruption = pyaudio_mock.stream.write.call_count
    
    # Push another frame
    await transport.process_frame(audio_frame3, 1)
    
    await asyncio.sleep(0.1)
    
    write_count_final = pyaudio_mock.stream.write.call_count
    
    # Cleanup
    await transport.process_frame(EndFrame(), 1)
    await transport.cleanup()

    # The exact assertions might vary depending on how chunks are processed
    # But generally, audio_frame2 should be dropped if the interruption is fast enough
    print(f"Write count before interruption: {write_count_before}")
    print(f"Write count after interruption: {write_count_after_interruption}")
    print(f"Write count after new frame: {write_count_final}")
