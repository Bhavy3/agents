import asyncio
import time
import pytest
from core.events.bus import EventBus
from core.events.event_types import EventType
from core.personality.presence_timing import PresenceTimingEngine
from core.orchestrator.response_gate import ResponseReadinessGate

@pytest.mark.asyncio
async def test_presence_timing_profiles():
    bus = EventBus()
    await bus.start()
    engine = PresenceTimingEngine(bus)
    
    # Test neutral (default base=300ms, variance=150ms)
    delay = await engine.get_response_delay(text_length=50)
    assert 0.3 <= delay <= 0.45
    
    # Test frustrated (base=50ms, variance=50ms)
    engine.update_profile("frustrated")
    delay = await engine.get_response_delay(text_length=50)
    assert 0.05 <= delay <= 0.10
    
    # Test confused (base=500ms, variance=300ms)
    engine.update_profile("confused")
    delay = await engine.get_response_delay(text_length=50)
    assert 0.5 <= delay <= 0.8
    
    # Test length penalty (neutral: base=100ms, variance=100ms, length penalty=200ms)
    engine.update_profile("neutral")
    delay = await engine.get_response_delay(text_length=150)
    assert 0.3 <= delay <= 0.4

    await bus.stop()

@pytest.mark.asyncio
async def test_response_readiness_gate():
    bus = EventBus()
    await bus.start()
    engine = PresenceTimingEngine(bus)
    engine.update_profile("frustrated") # Fast profile for test speed (50-100ms)
    gate = ResponseReadinessGate(bus, engine)
    
    start_time = time.perf_counter()
    is_ready = await gate.wait_for_readiness("turn_1", text_length=50)
    elapsed = time.perf_counter() - start_time
    
    assert is_ready is True
    assert elapsed >= 0.04 # Should wait at least the base delay
    
    await bus.stop()

@pytest.mark.asyncio
async def test_response_readiness_cancellation():
    bus = EventBus()
    await bus.start()
    engine = PresenceTimingEngine(bus)
    engine.update_profile("confused") # Slow profile so we can interrupt it
    gate = ResponseReadinessGate(bus, engine)
    
    async def run_wait():
        return await gate.wait_for_readiness("turn_2", text_length=50)
        
    task = asyncio.create_task(run_wait())
    
    # Let it start waiting
    await asyncio.sleep(0.05)
    
    # Cancel it (simulating user speaking again)
    gate.cancel_wait("turn_2")
    
    is_ready = await task
    assert is_ready is False # Should return False because it was cancelled
    await bus.stop()


@pytest.mark.asyncio
async def test_presence_timing_urgency_and_momentum_reduce_delay():
    bus = EventBus()
    await bus.start()
    engine = PresenceTimingEngine(bus)

    engine.update_profile("confused")
    slow_delay = await engine.get_response_delay(text_length=50)
    fast_delay = await engine.get_response_delay(text_length=50, urgency=1.0, momentum=1.0)

    assert fast_delay < slow_delay
    assert fast_delay >= 0.04

    await bus.stop()
