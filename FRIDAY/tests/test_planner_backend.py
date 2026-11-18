"""Plan with the strong model, execute with the fast one.

The 7B only authors the plan (one slow call).  The conversation and every tool
step stay on the primary model, so response latency is unchanged.  If the
strong endpoint is down the planner must fall back silently to the primary.
"""

import json
from types import SimpleNamespace

import pytest

from core.workflows.prompt_planner import PromptPlanner

GOOD_PLAN = [
    {
        "intent": "write_text_file",
        "parameters": {"file_path": "food/index.html", "content": "<h1>Food</h1>"},
    }
]
OTHER_PLAN = [
    {
        "intent": "write_text_file",
        "parameters": {"file_path": "other/index.html", "content": "<h1>Other</h1>"},
    }
]


class FakeClient:
    def __init__(self, payload, base_url="http://127.0.0.1:8080"):
        self.payload = payload
        self.base_url = base_url
        self.calls = 0

    async def generate(self, prompt, max_tokens=700):
        self.calls += 1
        return json.dumps(self.payload), SimpleNamespace(success=True, error=None)


@pytest.mark.asyncio
async def test_strong_model_writes_the_plan_and_primary_does_not(monkeypatch):
    monkeypatch.setenv("FRIDAY_PLANNER_MODEL", "7b")
    weak = FakeClient(OTHER_PLAN)
    strong = FakeClient(GOOD_PLAN, base_url="http://127.0.0.1:8081")
    planner = PromptPlanner(weak, strong_ollama_client=strong)
    monkeypatch.setattr(PromptPlanner, "_endpoint_healthy", lambda self: True)

    plan = await planner.create_plan_for_goal("prepare a project status note")

    assert plan == GOOD_PLAN
    assert planner.last_planner_backend == "strong"
    assert strong.calls == 1
    assert weak.calls == 0


@pytest.mark.asyncio
async def test_falls_back_to_primary_when_strong_is_down(monkeypatch):
    monkeypatch.setenv("FRIDAY_PLANNER_MODEL", "7b")
    weak = FakeClient(GOOD_PLAN)
    strong = FakeClient(OTHER_PLAN, base_url="http://127.0.0.1:8081")
    planner = PromptPlanner(weak, strong_ollama_client=strong)
    monkeypatch.setattr(PromptPlanner, "_endpoint_healthy", lambda self: False)

    plan = await planner.create_plan_for_goal("prepare a project status note")

    assert plan == GOOD_PLAN
    assert planner.last_planner_backend == "primary_strong_unavailable"
    assert strong.calls == 0
    assert weak.calls == 1


@pytest.mark.asyncio
async def test_disabled_unless_configured(monkeypatch):
    monkeypatch.delenv("FRIDAY_PLANNER_MODEL", raising=False)
    weak = FakeClient(GOOD_PLAN)
    strong = FakeClient(OTHER_PLAN, base_url="http://127.0.0.1:8081")
    planner = PromptPlanner(weak, strong_ollama_client=strong)

    plan = await planner.create_plan_for_goal("prepare a project status note")

    assert plan == GOOD_PLAN
    assert planner.last_planner_backend == "primary"
    assert strong.calls == 0


def test_no_strong_client_means_primary():
    planner = PromptPlanner(FakeClient(GOOD_PLAN))

    assert planner._planner_for_planning() is planner.planner


def test_endpoint_health_is_false_for_a_dead_port():
    strong = FakeClient(GOOD_PLAN, base_url="http://127.0.0.1:59999")
    planner = PromptPlanner(FakeClient(GOOD_PLAN), strong_ollama_client=strong)

    assert planner._endpoint_healthy() is False
