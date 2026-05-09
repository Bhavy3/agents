import asyncio
import time
import pytest

from core.audio.vad import VadWorker
from core.events.bus import EventBus
from core.events.event_types import EventType
from core.events.models import Event


@pytest.mark.asyncio
async def test_vad_speech_detection():
    bus = EventBus()
    await bus.start()
    
    worker = VadWorker(bus, silence_threshold=0.1, min_speech_duration=0.1, speech_inactivity_timeout=0.2)
    task = asyncio.create_task(worker.run())
    await asyncio.sleep(0.1)
    
    events = []
    async def track_events(e):
        events.append(e)
        
    bus.subscribe(EventType.SPEECH_STARTED, track_events)
    bus.subscribe(EventType.SPEECH_ENDED, track_events)
    bus.subscribe(EventType.SPEECH_SEGMENT_READY, track_events)
    
    # Simulate speech
    await bus.publish(Event.create(EventType.AUDIO_CHUNK_RECEIVED, {"chunk_size": 1024, "amplitude": 0.5, "timestamp": 1.0, "data": b"1"}, "test"))
    await asyncio.sleep(0.01)
    await bus.publish(Event.create(EventType.AUDIO_CHUNK_RECEIVED, {"chunk_size": 1024, "amplitude": 0.5, "timestamp": 1.1, "data": b"2"}, "test"))
    await asyncio.sleep(0.01)
    
    # Simulate silence (end of speech)
    await bus.publish(Event.create(EventType.AUDIO_CHUNK_RECEIVED, {"chunk_size": 1024, "amplitude": 0.0, "timestamp": 1.5, "data": b"3"}, "test"))
    await asyncio.sleep(0.1)
    
    await bus.drain()
    
    assert len(events) == 3
    assert events[0].event_type == EventType.SPEECH_STARTED
    assert events[1].event_type == EventType.SPEECH_ENDED
    assert events[2].event_type == EventType.SPEECH_SEGMENT_READY
    assert events[2].payload["audio_data"] == b"123"
    
    await worker.stop()
    await task
    await bus.stop()


@pytest.mark.asyncio
async def test_vad_noise_rejection():
    bus = EventBus()
    await bus.start()
    
    worker = VadWorker(bus, silence_threshold=0.1, min_speech_duration=0.5, speech_inactivity_timeout=0.2)
    task = asyncio.create_task(worker.run())
    await asyncio.sleep(0.1)
    
    events = []
    async def track_noise(e):
        events.append(e)
    bus.subscribe(EventType.SPEECH_NOISE_REJECTED, track_noise)
    
    # Simulate very short noise spike
    await bus.publish(Event.create(EventType.AUDIO_CHUNK_RECEIVED, {"chunk_size": 1024, "amplitude": 0.5, "timestamp": 1.0, "data": b"1"}, "test"))
    await asyncio.sleep(0.01)
    
    # Simulate silence
    await bus.publish(Event.create(EventType.AUDIO_CHUNK_RECEIVED, {"chunk_size": 1024, "amplitude": 0.0, "timestamp": 1.3, "data": b"2"}, "test"))
    await asyncio.sleep(0.1)
    
    await bus.drain()
    
    assert len(events) == 1
    assert events[0].payload["reason"] == "too_short"
    
    await worker.stop()
    await task
    await bus.stop()


@pytest.mark.asyncio
async def test_vad_max_duration_timeout():
    bus = EventBus()
    await bus.start()
    
    worker = VadWorker(bus, silence_threshold=0.1, max_speech_duration=0.2)
    task = asyncio.create_task(worker.run())
    await asyncio.sleep(0.1)
    
    events = []
    async def track_timeout(e):
        events.append(e)
    bus.subscribe(EventType.SPEECH_TIMEOUT, track_timeout)
    
    # Simulate start speech
    now = time.perf_counter()
    await bus.publish(Event.create(EventType.AUDIO_CHUNK_RECEIVED, {"chunk_size": 1024, "amplitude": 0.5, "timestamp": now, "data": b"1"}, "test"))
    
    # Wait for work() loop to trigger max duration
    await asyncio.sleep(0.6)
    
    await bus.drain()
    assert len(events) == 1
    assert events[0].payload["reason"] == "max_duration_exceeded"
    
    await worker.stop()
    await task
    await bus.stop()
