import pytest
from core.orchestrator.conversation import _WORKFLOW_REQUEST


@pytest.mark.parametrize("text,expected_match", [
    # True positives: explicit workflow and multi-step triggers
    ("run workflow to analyze logs", True),
    ("execute workflow now", True),
    ("debug the project", True),
    ("please fix the bug in auth", True),
    ("can you fix the code in main.py", True),
    ("search the web for BMW M8 top speed and remember it", True),
    ("first search for BMW M8 then save the result", True),
    ("First, search for BMW M8, then save the result", True),
    ("firstly, find the latest news, then summarize", True),
    ("first off, check the weather, then tell me", True),
    ("1) search for python docs, then read", True),
    ("1. search for python docs, then read", True),
    
    # False positives: must NOT trigger workflow
    ("How do I fix the bug in my code", False),
    ("did you fix the issue yesterday", False),
    ("I need to fix the code myself", False),
    ("prefix", False),
    ("can you fix my sentence", False),
    ("quick fix", False),
    ("affix this label", False),
    ("debug", False),
    ("what is the prefix of this word", False),
    ("can you debug me", False),
    ("fix dinner tonight", False),
    ("remember that my car is red", False),
    ("what's a workflow", False),
    ("what is a workflow", False),
    ("I first thought about it and then left", False),
    ("at first it was raining and then it stopped", False),
    ("first of all, I love you, and then some", False),
    ("the first time then", False),
])
def test_workflow_trigger_false_positives(text, expected_match):
    match = bool(_WORKFLOW_REQUEST.search(text))
    assert match is expected_match, f"Failed for text: '{text}'. Expected {expected_match}, got {match}"
