import pytest

from core.memory.explicit_requests import (
    extract_explicit_memory_content,
    is_personal_memory_query,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("remember that I prefer tea", "I prefer tea"),
        ("Remember my birthday is in May", "birthday is in May"),
        ("don't forget that my car is red", "my car is red"),
        ("save this: use short answers", "use short answers"),
        ("remember the movie", None),
        ("what do you remember about my car?", None),
    ],
)
def test_extract_explicit_memory_content(text, expected):
    assert extract_explicit_memory_content(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("what color is my car?", True),
        ("what do you remember about me?", True),
        ("tell me a joke", False),
    ],
)
def test_personal_memory_query_detection(text, expected):
    assert is_personal_memory_query(text) is expected
