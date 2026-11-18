"""An n8n schedule request must produce a workflow with a real trigger.

Live defect: the planner sent only {"name": "Daily Digest"} and n8n happily
created an empty workflow, which was then reported as success.
"""

import json

from core.workflows.prompt_planner import PromptPlanner


def _plan(goal):
    plan = PromptPlanner._deterministic_fallback(goal)
    assert plan is not None, f"no plan for: {goal}"
    return plan


def test_daily_digest_gets_a_cron_trigger():
    plan = _plan("create an n8n workflow called Daily Digest that runs every morning at 7")

    assert len(plan) == 1
    step = plan[0]
    assert step["intent"] == "n8n_create_workflow"
    assert step["parameters"]["name"].lower() == "daily digest"

    workflow = json.loads(step["parameters"]["workflow_json"])
    assert len(workflow["nodes"]) == 1
    node = workflow["nodes"][0]
    assert node["type"] == "n8n-nodes-base.scheduleTrigger"
    expression = node["parameters"]["rule"]["interval"][0]["expression"]
    assert expression == "0 7 * * *"


def test_evening_time_is_24_hour():
    plan = _plan("build an n8n workflow called Report that runs at 7 pm")
    workflow = json.loads(plan[0]["parameters"]["workflow_json"])

    assert workflow["nodes"][0]["parameters"]["rule"]["interval"][0]["expression"] == "0 19 * * *"


def test_minutes_are_preserved():
    plan = _plan("create an n8n workflow called Sweep that runs at 6:30")
    workflow = json.loads(plan[0]["parameters"]["workflow_json"])

    assert workflow["nodes"][0]["parameters"]["rule"]["interval"][0]["expression"] == "30 6 * * *"


def test_non_n8n_goal_is_untouched():
    assert PromptPlanner._n8n_plan("build a docker compose project") is None
    assert PromptPlanner._n8n_plan("make a food website") is None
