"""Unit tests for Ω.6 Emotional Presence — Tone modulation."""
import logging
from unittest.mock import AsyncMock, MagicMock
import pytest

from core.cognition.tone_detector import detect_tone
from core.cognition.cognitive_state import CognitiveStateEngine
from core.events.bus import EventBus
from core.llm.llm_worker import LlmWorker
from core.orchestrator.conversation import OrchestratorWorker
from core.router.rules import Intent, IntentName
from core.tools.tool_registry import ToolRegistry


def test_tone_detector_confident():
    assert detect_tone("can you help me") == "confident"


def test_tone_detector_cautious():
    assert detect_tone("not sure if this will work") == "cautious"


def test_tone_detector_curious():
    assert detect_tone("explore the deep dive") == "curious"


def test_tone_detector_warm():
    assert detect_tone("I'm frustrated, help me") == "warm"


def test_tone_detector_explicit_confidence():
    assert detect_tone("I am certain this is the right answer.") == "confident"


def test_tone_detector_discouragement_is_warm():
    assert detect_tone("I feel discouraged and could use encouragement.") == "warm"


def test_tone_detector_neutral_instruction():
    assert detect_tone("Please explain how a database index works.") == "neutral"


def test_tone_detector_factual_instruction():
    assert detect_tone("Give the exact date and numeric measurements only.") == "factual"


def test_previous_warm_turn_does_not_override_current_neutral_or_factual_tone():
    history = ["I feel discouraged and could use encouragement."]

    assert detect_tone("Please explain how a database index works.", history=history) == "neutral"
    assert detect_tone("Give the exact date and numeric measurements only.", history=history) == "factual"


@pytest.mark.asyncio
async def test_emotional_tone_changes_delivery_prompt_only():
    bus = EventBus()
    await bus.start()
    router = AsyncMock()
    router.route.return_value = Intent(
        IntentName.CHAT,
        1.0,
        {"response_text": "answer"},
        source="unit_test",
    )
    engine = CognitiveStateEngine(bus)
    engine.current_tone = "warm"
    orchestrator = OrchestratorWorker(bus, router, MagicMock(), cognitive_state=engine)
    orchestrator.active_turn_id = "turn-tone-test"
    orchestrator.response_gate.wait_for_readiness = AsyncMock(return_value=True)
    orchestrator._request_memory_context = AsyncMock(return_value="")
    orchestrator.injector.get_style_instructions = MagicMock(return_value="base personality")

    await orchestrator._route_and_execute("Explain this", "turn-tone-test", "corr-tone-test")

    route_kwargs = router.route.await_args.kwargs
    assert "supportive, friendly, and compassionate" not in route_kwargs["personality_instructions"]
    assert "supportive, friendly, and compassionate" in route_kwargs["chat_instructions"]
    assert "base personality" in route_kwargs["personality_instructions"]
    assert "base personality" in route_kwargs["chat_instructions"]
    await bus.stop()


@pytest.mark.asyncio
async def test_tone_context_is_snapshotted_for_delayed_turn():
    bus = EventBus()
    await bus.start()
    router = AsyncMock()
    router.route.return_value = Intent(IntentName.CHAT, 1.0, {"response_text": "answer"}, source="unit_test")
    engine = CognitiveStateEngine(bus)
    orchestrator = OrchestratorWorker(bus, router, MagicMock(), cognitive_state=engine)
    orchestrator.active_turn_id = "turn-tone-snapshot"
    orchestrator.response_gate.wait_for_readiness = AsyncMock(return_value=True)
    orchestrator._request_memory_context = AsyncMock(return_value="")
    orchestrator.injector.get_style_instructions = MagicMock(return_value="base personality")

    warm_context = "You are supportive, friendly, and compassionate. Show empathy and care."
    await orchestrator._route_and_execute(
        "Explain this",
        "turn-tone-snapshot",
        "corr-tone-snapshot",
        tone_context=warm_context,
    )

    assert warm_context in router.route.await_args.kwargs["chat_instructions"]
    await bus.stop()


@pytest.mark.asyncio
async def test_tone_shift_logged(caplog):
    engine = CognitiveStateEngine(MagicMock())
    engine.current_tone = "confident"
    with caplog.at_level(logging.DEBUG):
        await engine.update_tone("explore why")
    assert engine.current_tone == "curious"
    assert "tone_shift: confident → curious" in caplog.text


def test_tone_context_string():
    engine = CognitiveStateEngine(MagicMock())
    for tone in ["confident", "cautious", "curious", "warm"]:
        engine.current_tone = tone
        ctx = engine.get_tone_context()
        assert ctx
        assert len(ctx) > 10
        assert any(word in ctx.lower() for word in [tone, "direct", "measured", "inquisitive", "supportive"])


@pytest.mark.parametrize(
    ("tone", "expected_phrase"),
    [("neutral", "neutral"), ("factual", "evidence-focused")],
)
def test_tone_context_supports_neutral_and_factual_delivery(tone, expected_phrase):
    engine = CognitiveStateEngine(MagicMock())
    engine.current_tone = tone

    assert expected_phrase in engine.get_tone_context().lower()


def test_system_prompt_modulation():
    engine = CognitiveStateEngine(MagicMock())
    engine.current_tone = "confident"
    worker = LlmWorker(cognitive_state=engine)
    prompt = worker._build_system_prompt("Base instructions")
    assert "You are direct, assured, and confident." in prompt
    assert "You are FRIDAY, a local-first JARVIS-style AI assistant" in prompt
    assert "Base instructions" in prompt


@pytest.mark.asyncio
async def test_tone_never_affects_tool_selection():
    registry = ToolRegistry()
    base_tools = set(registry.list_tools())
    engine = CognitiveStateEngine(MagicMock())
    for tone in ["confident", "cautious", "curious", "warm"]:
        engine.current_tone = tone
        assert set(registry.list_tools()) == base_tools


def test_tone_resets_on_restart():
    engine = CognitiveStateEngine(MagicMock())
    assert engine.current_tone == "curious"
    engine.current_tone = "confident"
    assert engine.current_tone == "confident"
    restarted_engine = CognitiveStateEngine(MagicMock())
    assert restarted_engine.current_tone == "curious"


@pytest.mark.asyncio
async def test_tone_smooth_transition(caplog):
    engine = CognitiveStateEngine(MagicMock())
    assert engine.current_tone == "curious"
    with caplog.at_level(logging.DEBUG):
        await engine.update_tone("tell me something")
    assert engine.current_tone == "curious"
    assert "tone_shift" not in caplog.text
