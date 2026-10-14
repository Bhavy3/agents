#!/usr/bin/env python3
"""
Check if FrameProcessor can be imported and used
"""

print("=== Checking pipecat imports ===")

# First try direct import
try:
    from pipecat.processors.frame_processor import FrameProcessor
    print(f"✓ Direct import of FrameProcessor succeeded: {FrameProcessor}")
    print(f"  Module: {FrameProcessor.__module__}")
except Exception as e:
    print(f"✗ Direct import of FrameProcessor failed: {e}")

# Try importing as it appears in pipecat_worker.py
try:
    from pipecat.pipeline.pipeline import Pipeline
    from pipecat.pipeline.task import PipelineTask
    from pipecat.pipeline.runner import PipelineRunner
    from pipecat.transports.local.audio import LocalAudioTransport, LocalAudioTransportParams
    from pipecat.services.whisper.stt import WhisperSTTService
    from pipecat.audio.vad.silero import SileroVADAnalyzer
    from pipecat.audio.vad.vad_analyzer import VADParams
    from pipecat.processors.audio.vad_processor import VADProcessor
    from pipecat.processors.frame_processor import FrameProcessor
    from pipecat.frames.frames import TranscriptionFrame, AudioRawFrame, OutputAudioRawFrame, CancelFrame, InterruptionFrame
    print("✓ All imports from AGENTS.md succeed")
    print(f"  FrameProcessor: {FrameProcessor}")
    print(f"  Module: {FrameProcessor.__module__}")
except Exception as e:
    print(f"✗ Import from AGENTS.md failed: {e}")

# Try creating a minimal FrameProcessor subclass like AecProcessor
try:
    from pipecat.processors.frame_processor import FrameProcessor

    class TestProcessor(FrameProcessor):
        pass

    print(f"✓ Can subclass FrameProcessor: {TestProcessor}")
except Exception as e:
    print(f"✗ Cannot subclass FrameProcessor: {e}")

print("\n=== Checking pipecat version ===")
try:
    import pipecat
    print(f"Pipecat version: {pipecat.__version__}")

    # Check what's available in pipecat.processors
    import pipecat.processors
    print(f"Available processors: {[x for x in dir(pipecat.processors) if not x.startswith('_')]}")

    if hasattr(pipecat.processors, 'frame_processor'):
        print(f"frame_processor module available: {pipecat.processors.frame_processor}")

    # Try to find FrameProcessor in pipecat.processors
    if hasattr(pipecat.processors, 'FrameProcessor'):
        print(f"FrameProcessor directly in pipecat.processors: {pipecat.processors.FrameProcessor}")
    else:
        print("FrameProcessor NOT directly in pipecat.processors")

except Exception as e:
    print(f"✗ Error checking pipecat version: {e}")

print("\n=== Done ===")