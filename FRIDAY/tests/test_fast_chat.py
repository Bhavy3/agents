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
