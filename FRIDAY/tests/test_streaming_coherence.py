import asyncio
import pytest
from core.events.bus import EventBus
from core.events.event_types import EventType
from core.events.models import Event
from core.audio.transcript_stabilizer import TranscriptStabilizer, StabilizerConfig
from core.orchestrator.response_buffer import SemanticResponseBuffer, BufferConfig


@pytest.mark.asyncio
async def test_transcript_stabilizer_deduplication():
    bus = EventBus()
    await bus.start()
    
    config = StabilizerConfig(min_stable_frames=2, meaningful_delta_length=4)
    stabilizer = TranscriptStabilizer(bus, config)
    
    # 1. Unstable partials (jitter)
    await stabilizer.process_partial("seg_1", "h")
    await stabilizer.process_partial("seg_1", "he")
    await stabilizer.process_partial("seg_1", "hel")
    await asyncio.sleep(0.01)
    
    # Shouldn't emit yet, frames too low and delta too small
    assert stabilizer._last_emitted_text == ""
    
    # 2. Stable partials
    await stabilizer.process_partial("seg_1", "hello")
    await stabilizer.process_partial("seg_1", "hello")
    await stabilizer.process_partial("seg_1", "hello")
    await asyncio.sleep(0.01)
    
    # Now it should emit/set stable text
    assert stabilizer._last_emitted_text == "hello"
    
    # 3. Meaningful delta (addition)
    await stabilizer.process_partial("seg_1", "hello there friend")
    await asyncio.sleep(0.01)
    
    # Emits instantly because of delta length
    assert stabilizer._last_emitted_text == "hello there friend"
    
    # 4. Revision (dropped token)
    await stabilizer.process_partial("seg_1", "something completely different")
    await asyncio.sleep(0.01)
    
    # Text is not emitted yet as stable, it's just set as the current stable text
    assert stabilizer._current_stable_text == "something completely different"
    assert stabilizer._frames_stable == 0

    await bus.stop()


@pytest.mark.asyncio
async def test_semantic_response_buffer_flushing():
    bus = EventBus()
    await bus.start()
    
    config = BufferConfig(min_chunk_length=10)
    buffer = SemanticResponseBuffer(bus, config)
    buffer.set_turn_id("turn_1")
    
    events = []
    async def on_event(e):
        if e.payload.get("status") == "partial" and "text" in e.payload:
            events.append(e)
    
    bus.subscribe(EventType.ASSISTANT_RESPONSE, on_event)
    
    # Feed tokens
    tokens = ["I ", "am ", "think", "ing", ". ", "And ", "now ", "I ", "will ", "speak", "!"]
    
    for t in tokens:
        await buffer.ingest_token(t)
        
    await asyncio.sleep(0.01)
    
    assert len(events) == 2
    
    assert events[0].payload["text"] == "I am thinking."
    assert events[1].payload["text"] == "And now I will speak!"
    
    # Feed remaining text
    await buffer.ingest_token(" But wait")
    await buffer.flush_final()
    
    await asyncio.sleep(0.01)
    
    assert len(events) == 3
    assert events[2].payload["text"] == "But wait"
    assert events[2].payload["is_final"] == True

    await bus.stop()
