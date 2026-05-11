import pytest
import asyncio
from core.personality.models import PersonaMode, EmotionState, StyleConfig
from core.personality.style_engine import StyleEngine
from core.personality.emotion import EmotionClassifier
from core.personality.prompt_personality import PersonalityPromptInjector


def test_style_engine_switching():
    engine = StyleEngine()
    
    # Engineering mode - Calm
    config = engine.compute_style(PersonaMode.ENGINEERING, EmotionState.CALM)
    assert config.tone == "focused"
    assert config.verbosity == "concise"
    
    # Teaching mode - Confused
    config = engine.compute_style(PersonaMode.TEACHING, EmotionState.CONFUSED)
    assert config.tone == "clarifying"
    assert config.verbosity == "detailed"
    assert config.pacing == "slow"
    
    # Stress/Frustrated override
    config = engine.compute_style(PersonaMode.ENGINEERING, EmotionState.FRUSTRATED)
    assert config.tone == "direct"
    assert config.verbosity == "concise"
    assert config.pacing == "fast"


def test_emotion_detection():
    classifier = EmotionClassifier()
    
    assert classifier.detect_emotion("This is stupid and wrong!!") == EmotionState.FRUSTRATED
    assert classifier.detect_emotion("I am so confused why this is happening??") == EmotionState.CONFUSED
    assert classifier.detect_emotion("Hurry up, this is urgent ASAP") == EmotionState.URGENT
    assert classifier.detect_emotion("Normal day in the lab.") == EmotionState.CALM


def test_prompt_injection():
    injector = PersonalityPromptInjector()
    config = StyleConfig(tone="patient", verbosity="detailed", pacing="slow", humor_level=0.1)
    
    prompt = injector.get_style_instructions(config, PersonaMode.TEACHING)
    assert "[PERSONALITY_GUIDELINES]" in prompt
    assert "Tonal guideline: patient" in prompt
    assert "Explain concepts step-by-step" in prompt


@pytest.mark.asyncio
async def test_presence_thinking_delay():
    from core.personality.presence import PresenceManager
    manager = PresenceManager()
    
    # Fast pacing
    config_fast = StyleConfig(tone="alert", verbosity="concise", pacing="fast")
    start = asyncio.get_event_loop().time()
    await manager.simulate_thinking_delay(config_fast, 0.1)
    end = asyncio.get_event_loop().time()
    assert (end - start) < 1.5
    
    # Slow pacing
    config_slow = StyleConfig(tone="patient", verbosity="detailed", pacing="slow")
    start = asyncio.get_event_loop().time()
    await manager.simulate_thinking_delay(config_slow, 0.5)
    end = asyncio.get_event_loop().time()
    assert (end - start) > 0.4


@pytest.mark.asyncio
async def test_personality_worker_integration():
    from core.events.bus import EventBus
    from core.events.event_types import EventType
    from core.events.models import Event
    from core.personality.personality_worker import PersonalityWorker
    
    bus = EventBus()
    worker = PersonalityWorker(bus)
    
    await bus.start()
    await worker.start()
    await asyncio.sleep(0.1)
    
    updates = []
    async def on_update(e):
        updates.append(e)
        
    bus.subscribe(EventType.PERSONALITY_STYLE_UPDATED, on_update)
    
    # Send a frustrated message
    await bus.publish(Event.create(
        EventType.USER_TEXT_RECEIVED,
        {"text": "This is totally wrong and stupid!"},
        "test"
    ))
    
    # Wait for processing
    await asyncio.sleep(0.2)
    
    assert len(updates) > 0
    assert updates[0].payload["emotion_state"] == EmotionState.FRUSTRATED
    assert updates[0].payload["style_config"]["tone"] == "direct"
    
    await worker.stop()
    await bus.stop()
