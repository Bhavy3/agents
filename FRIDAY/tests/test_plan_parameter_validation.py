"""A plan must not be accepted when a step omits a parameter the tool needs.

Live defect: a plan containing `open_section` with no `url` passed validation
and then failed during execution with
"BrowserTools.open_section() missing 1 required positional argument: 'url'".
"""

import pytest

from core.tools.tool_registry import ToolRegistry
from core.workflows.planner import BoundedPlanner


@pytest.fixture()
def planner():
    return BoundedPlanner(ollama_client=None, tool_registry=ToolRegistry())


def test_open_section_without_url_is_rejected(planner):
    with pytest.raises(ValueError) as excinfo:
        planner.validate_plan(
            [{"intent": "open_section", "parameters": {}}],
            original_goal="build me a simple food website",
        )

    assert "url" in str(excinfo.value)
    assert "section" in str(excinfo.value)


def test_open_section_with_url_is_accepted(planner):
    plan = planner.validate_plan(
        [{
            "intent": "open_section",
            "parameters": {"url": "https://example.com/pricing", "section": "pricing"},
        }],
        original_goal="open the pricing section of example.com",
    )

    assert plan[0]["intent"] == "open_section"
    assert plan[0]["parameters"]["url"] == "https://example.com/pricing"


def test_declared_required_parameters_still_enforced(planner):
    with pytest.raises(ValueError) as excinfo:
        planner.validate_plan(
            [{"intent": "write_text_file", "parameters": {"file_path": "a.txt"}}],
            original_goal="write a file",
        )

    assert "content" in str(excinfo.value)


def test_signature_helper_reports_only_required_names(planner):
    assert planner._signature_missing_parameters("open_section", {}) == ["url", "section"]
    assert planner._signature_missing_parameters(
        "open_section", {"url": "x", "section": "y"}
    ) == []
    assert planner._signature_missing_parameters("not_a_tool", {}) == []
