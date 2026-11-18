import pytest

from core.router.rules import IntentName, fast_chat_intent


@pytest.mark.parametrize(
    "text",
    [
        "so how are you doing to day",
        "how are you doing today?",
        "How are you doing today!",
    ],
)
def test_small_talk_variants_use_fast_chat(text):
    intent = fast_chat_intent(text)

    assert intent is not None
    assert intent.name == IntentName.CHAT
    assert intent.source == "fast_chat"


def test_fast_chat_prompt_keeps_personality_instructions():
    from core.orchestrator.conversation import OrchestratorWorker

    prompt = OrchestratorWorker._build_fast_chat_prompt(
        "so how are you doing to day",
        None,
        "Use a focused, concise engineering tone.",
    )

    assert "Use a focused, concise engineering tone." in prompt
    assert "User: so how are you doing to day" in prompt
