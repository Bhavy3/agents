"""Refusals must say why: no vague 'could not create a plan' dead ends."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from core.orchestrator.workflow_trigger import _WORKFLOW_REQUEST, refusal_message
from core.tools.tool_registry import ToolRegistry
from core.workflows.prompt_planner import PromptPlanner


class _EmptyPlanClient:
    """Returns an empty JSON list, the shape a planner produces when nothing fits."""

    def __init__(self) -> None:
        self.calls = 0

    async def generate(self, prompt: str, max_tokens: int = 700):
        self.calls += 1
        return "[]", SimpleNamespace(success=True, error=None)


def test_empty_plan_is_reported_as_missing_capability():
    message = refusal_message("invalid_plan", "Plan cannot be empty")
    assert message == "I don't have a tool that can do that yet, so I did not guess at a plan."


def test_specific_validator_detail_is_surfaced():
    message = refusal_message(
        "invalid_plan", "Step 1 ('desktop_type') is missing required parameter(s): text"
    )
    assert "missing required parameter" in message


def test_unauthorized_remember_keeps_its_own_message():
    assert "state it explicitly" in refusal_message("remember_not_authorized", None)


def test_unsafe_substitution_keeps_its_own_message():
    assert "sensitive parameters" in refusal_message("unsafe_parameter_substitution", None)


def test_planner_service_error_is_distinct():
    assert "planner service error" in refusal_message("llm_error", None)


def test_unknown_reason_still_says_something_useful():
    message = refusal_message(None, None)
    assert message
    assert "plan" in message.lower()


def test_prompt_planner_preserves_the_validator_detail():
    planner = PromptPlanner(_EmptyPlanClient(), tool_registry=ToolRegistry())

    steps = asyncio.run(planner.create_plan_for_goal("summarize my notes into three bullets"))

    assert steps == []
    assert planner.last_rejection_reason == "invalid_plan"
    assert planner.last_rejection_detail
    assert "cannot be empty" in planner.last_rejection_detail
    # The refusal the user hears must name the real cause, not a generic line.
    assert "don't have a tool" in refusal_message(
        planner.last_rejection_reason, planner.last_rejection_detail
    )


# --- routing: an honest refusal is useless if the turn never reaches a planner ---
def test_a_request_to_build_a_workflow_reaches_the_planner():
    assert _WORKFLOW_REQUEST.search("build this workflow for me")
    assert _WORKFLOW_REQUEST.search("can you automate a workflow for invoices")


def test_a_question_about_workflows_stays_a_conversation():
    assert not _WORKFLOW_REQUEST.search("what is a workflow exactly")


def test_a_build_request_still_reaches_the_planner():
    assert _WORKFLOW_REQUEST.search("make a food website plan and then start coding")


# --- the deterministic fallback must not hijack another platform's goal ---
def test_n8n_goal_is_not_hijacked_into_a_website_scaffold():
    goal = "build an n8n workflow that checks a website every hour and emails me when it changes"
    plan = PromptPlanner._deterministic_fallback(goal)

    # The fallback may now build the automation itself, but it must never
    # answer an n8n request by scaffolding a website.
    if plan is not None:
        intents = [step["intent"] for step in plan]
        assert intents and all(intent == "n8n_create_workflow" for intent in intents), intents


def test_docker_goal_is_not_hijacked_either():
    assert PromptPlanner._deterministic_fallback("build a docker compose project") is None


def test_a_real_website_request_still_gets_its_scaffold():
    plan = PromptPlanner._deterministic_fallback("make a food website plan and then start coding")
    assert plan is not None
    assert [step["intent"] for step in plan] == [
        "write_text_file", "write_text_file", "write_text_file",
        "browser_open", "browser_snapshot",
    ]


def test_accepted_plan_clears_the_rejection_detail():
    class _GoodPlanClient:
        async def generate(self, prompt: str, max_tokens: int = 700):
            return (
                '[{"intent": "get_time", "parameters": {}}]',
                SimpleNamespace(success=True, error=None),
            )

    planner = PromptPlanner(_GoodPlanClient(), tool_registry=ToolRegistry())
    steps = asyncio.run(planner.create_plan_for_goal("what time is it"))

    assert len(steps) == 1
    assert planner.last_rejection_reason is None
    assert planner.last_rejection_detail is None
