"""The website fallback must build the requested subject, not a placeholder.

Live defect: "build me a simple food website" produced website/index.html
containing "<h1>website</h1>" and "Project scaffold created by FRIDAY."
"""

from core.workflows.prompt_planner import PromptPlanner
import pytest


def _plan(goal: str):
    plan = PromptPlanner._deterministic_fallback(goal)
    assert plan is not None, f"no fallback plan for: {goal}"
    return {
        step["parameters"]["file_path"]: step["parameters"]["content"]
        for step in plan if step["intent"] == "write_text_file"
    }


def test_food_website_plan_builds_and_previews_a_complete_site():
    plan = PromptPlanner._deterministic_fallback("build me a simple food website and run it")
    assert plan is not None
    intents = [step["intent"] for step in plan]
    files = {
        step["parameters"]["file_path"]: step["parameters"]["content"]
        for step in plan
        if step["intent"] == "write_text_file"
    }

    index_path = next(path for path in files if path.endswith("/index.html"))
    project = index_path.removesuffix("/index.html")
    html = files[index_path]
    assert "<h1>Food</h1>" in html
    assert "<title>Food</title>" in html
    assert "Replace this paragraph" not in html
    assert "A starting point" not in html
    assert "Project scaffold created by FRIDAY" not in html
    assert f"{project}/style.css" in files
    assert f"{project}/app.js" in files
    assert "<script src=\"app.js\"" in html
    assert "<link rel=\"stylesheet\" href=\"style.css\"" in html
    assert intents[-2:] == ["browser_open", "browser_snapshot"]
    assert plan[-2]["parameters"]["url"] == f"workspace://{project}/index.html"


def test_explicit_name_still_wins():
    files = _plan("build a website called harborkitchen")

    index_path = next(path for path in files if path.endswith("/index.html"))
    assert index_path.startswith("harborkitchen-")
    assert "<h1>Harborkitchen</h1>" in files[index_path]


def test_subject_after_about_is_detected():
    assert PromptPlanner._website_subject("make a website about coffee roasting") == "coffee roasting"


def test_filler_only_request_keeps_a_generic_name():
    assert PromptPlanner._website_subject("build me a simple website") == ""
    files = _plan("build me a simple website")
    assert any(path.startswith("website-") and path.endswith("/index.html") for path in files)


def test_website_fallback_has_three_build_steps_and_two_verification_steps():
    plan = PromptPlanner._deterministic_fallback("build me a simple food website")
    assert len(plan) == 5
    assert [step["intent"] for step in plan] == [
        "write_text_file", "write_text_file", "write_text_file",
        "browser_open", "browser_snapshot",
    ]


@pytest.mark.asyncio
async def test_website_build_uses_verified_local_preview_plan_without_llm():
    class NoModel:
        async def generate(self, *_args, **_kwargs):
            raise AssertionError("website scaffolding must not depend on LLM plan quality")

    planner = PromptPlanner(NoModel())
    plan = await planner.create_plan_for_goal("Build me a food website and run it")

    assert planner.last_planner_backend == "deterministic_website_build"
    assert planner.planner.validate_plan(plan, original_goal="Build me a food website and run it") == plan
