import pytest

from core.router.arithmetic import evaluate_arithmetic, is_percent_of_question
from core.router.rules import IntentName, route_by_rules


@pytest.mark.parametrize(
    "text,expected",
    [
        ("what is 15 percent of 80", "15% of 80 = 12"),
        ("what's 15 percent of 80", "15% of 80 = 12"),
        ("15 percent of 80", "15% of 80 = 12"),
        ("10% of 50", "10% of 50 = 5"),
        ("calculate 50 percent of 200", "50% of 200 = 100"),
        ("what is 12.5 percent of 80", "12.5% of 80 = 10"),
        ("what is 15 percentage of 80", "15% of 80 = 12"),
        ("what is 15 % of 80", "15% of 80 = 12"),
    ],
)
def test_percent_of_forms_compute_deterministically(text, expected):
    assert evaluate_arithmetic(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "what is 15 percent of 80",
        "10% of 50",
    ],
)
def test_percent_of_routes_to_deterministic_math(text):
    intent = route_by_rules(text)

    assert intent is not None
    assert intent.name == IntentName.CHAT
    assert intent.source == "deterministic_math"


@pytest.mark.parametrize(
    "text",
    [
        "what is the capital of France",
        "what is an event bus",
        "call 555-123-4567",
        "what happened on 2024-01-15",
        "version 1.2.3 release notes",
        "15 % 80",
        "what is 15 percent of",
        "percent of 80",
    ],
)
def test_non_math_and_collision_inputs_are_not_percent_of(text):
    assert not is_percent_of_question(text)


def test_bare_modulo_expression_unchanged():
    # "15 % 80" keeps its modulo semantics; only the "of" form is percent
    assert evaluate_arithmetic("15 % 80") == "15 % 80 = 15"


def test_is_percent_of_question_positive():
    assert is_percent_of_question("what is 15 percent of 80")
    assert is_percent_of_question("10% of 50")


@pytest.mark.parametrize(
    "text",
    [
        "what is 15 percent of 80",
        "10% of 50",
    ],
)
def test_fast_chat_does_not_claim_percent_questions(text):
    # The typed-input path consults fast_chat_intent BEFORE route_by_rules;
    # it must leave deterministic math to the rules router.
    from core.router.rules import fast_chat_intent

    assert fast_chat_intent(text) is None


def test_identity_line_present_in_personality_instructions():
    from core.personality.models import PersonaMode, StyleConfig
    from core.personality.prompt_personality import PersonalityPromptInjector

    injector = PersonalityPromptInjector()
    instructions = injector.get_style_instructions(
        StyleConfig(tone="focused", verbosity="concise", pacing="normal", humor_level=0.0),
        PersonaMode.ENGINEERING,
    )

    assert "You are FRIDAY" in instructions
    assert "never state or imply an underlying model identity" in instructions
