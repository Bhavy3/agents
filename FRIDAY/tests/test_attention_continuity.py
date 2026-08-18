import asyncio
import time
import pytest
from core.events.bus import EventBus
from core.events.event_types import EventType
from core.orchestrator.attention_state import AttentionStateEngine
from core.orchestrator.context_resolver import ContextResolver

def test_attention_momentum_and_decay():
    bus = EventBus()
    engine = AttentionStateEngine(bus)
    
    # Fast decay for test
    engine.decay_rate_per_second = 0.5
    
    assert engine.get_current_momentum() == 0.0
    
    engine.add_momentum(1.0)
    assert engine.get_current_momentum() == pytest.approx(1.0, abs=0.01)
    
    time.sleep(0.5) # Simulate time passing
    momentum = engine.get_current_momentum()
    
    assert 0.4 <= momentum <= 0.8
    
    # It shouldn't drop below 0
    time.sleep(1.5)
    assert engine.get_current_momentum() == 0.0

def test_attention_entities_update():
    bus = EventBus()
    engine = AttentionStateEngine(bus)
    
    engine.update_attention(subject="coding", task="refactoring", entities=["script.py"])
    
    assert engine.state.active_subject == "coding"
    assert engine.state.active_task == "refactoring"
    assert engine.state.recent_entities == ["script.py"]
    assert engine.state.momentum == 1.0
    
    engine.update_attention(entities=["main.py", "utils.py"])
    
    # Keeps max 5 recent entities
    assert engine.state.recent_entities == ["script.py", "main.py", "utils.py"]
    
def test_context_resolution():
    bus = EventBus()
    engine = AttentionStateEngine(bus)
    resolver = ContextResolver(engine)
    
    # Update attention state
    engine.update_attention(subject="the login page", task="fixing a bug", entities=["login.html", "auth.js"])
    
    # Simulate an immediate follow-up (high momentum)
    engine.add_momentum(1.0)
    
    text = "fix it please"
    assert resolver.contains_reference(text) is True
    
    resolved_text, was_resolved, desc = resolver.resolve_references(text)
    
    assert was_resolved is True
    assert "active task" in desc
    assert "login.html" in desc
    assert "fix it please (" in resolved_text
    
    # Test momentum decay failing to resolve
    engine.state.last_updated = time.perf_counter() - 100.0 # Force momentum to 0
    
    resolved_text, was_resolved, desc = resolver.resolve_references(text)
    
    assert was_resolved is False # Should fail because momentum is too low
    assert resolved_text == text
