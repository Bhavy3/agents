import pytest
from unittest.mock import AsyncMock
from core.workflows.planner import BoundedPlanner, MAX_WORKFLOW_STEPS
from core.tools.tool_registry import ToolRegistry


def _make_mock_ollama(response_text: str, success: bool = True):
    client = AsyncMock()
    metrics = AsyncMock()
    metrics.success = success
    client.generate.return_value = (response_text, metrics)
    return client


@pytest.mark.asyncio
async def test_planner_valid_json_plan():
    valid_json = """[
        {"intent": "search_web", "parameters": {"query": "BMW M8 top speed"}},
        {"intent": "write_text_file", "parameters": {"file_path": "car.txt", "content": "{{step_0_result}}"}}
    ]"""
    client = _make_mock_ollama(valid_json)
    planner = BoundedPlanner(client)
    plan = await planner.plan("Search BMW M8 and save it")
    assert len(plan) == 2
    assert plan[0]["intent"] == "search_web"
    assert plan[0]["parameters"]["query"] == "BMW M8 top speed"
    assert plan[1]["intent"] == "write_text_file"


def test_search_web_input_alias_normalizes_to_query():
    """Accept the common planner alias while emitting the tool's required query key."""
    planner = BoundedPlanner(_make_mock_ollama("[]"))
    plan = planner.validate_plan(
        [{"intent": "search_web", "parameters": {"input": "capital of France"}}],
        original_goal="First search for the capital of France, then remember it.",
    )

    assert plan == [{"intent": "search_web", "parameters": {"query": "capital of France"}}]


def test_remember_input_alias_normalizes_to_fact():
    planner = BoundedPlanner(_make_mock_ollama("[]"))
    plan = planner.validate_plan(
        [{"intent": "remember", "parameters": {"input": "Paris is the capital of France."}}],
        original_goal="First search for the capital of France, then remember it.",
    )

    assert plan == [{"intent": "remember", "parameters": {"fact": "Paris is the capital of France."}}]


def test_empty_remember_fact_after_search_uses_previous_result():
    planner = BoundedPlanner(_make_mock_ollama("[]"))
    plan = planner.validate_plan(
        [
            {"intent": "search_web", "parameters": {"query": "capital of France"}},
            {"intent": "remember", "parameters": {"fact": ""}},
        ],
        original_goal="First search for the capital of France, then remember it.",
    )

    assert plan[1]["parameters"]["fact"] == "{{step_0_result}}"


def test_missing_remember_fact_after_search_uses_previous_result():
    planner = BoundedPlanner(_make_mock_ollama("[]"))
    plan = planner.validate_plan(
        [
            {"intent": "search_web", "parameters": {"query": "capital of France"}},
            {"intent": "remember", "parameters": {}},
        ],
        original_goal="First search for the capital of France, then remember it.",
    )

    assert plan[1]["parameters"]["fact"] == "{{step_0_result}}"


def test_null_remember_fact_after_search_uses_previous_result():
    planner = BoundedPlanner(_make_mock_ollama("[]"))
    plan = planner.validate_plan(
        [
            {"intent": "search_web", "parameters": {"query": "capital of France"}},
            {"intent": "remember", "parameters": {"fact": None}},
        ],
        original_goal="First search for the capital of France, then remember it.",
    )

    assert plan[1]["parameters"]["fact"] == "{{step_0_result}}"


def test_self_referencing_remember_fact_uses_previous_search_result():
    planner = BoundedPlanner(_make_mock_ollama("[]"))
    plan = planner.validate_plan(
        [
            {"intent": "search_web", "parameters": {"query": "capital of France"}},
            {"intent": "remember", "parameters": {"fact": "{{step_1_result}}"}},
        ],
        original_goal="First search for the capital of France, then remember it.",
    )

    assert plan[1]["parameters"]["fact"] == "{{step_0_result}}"


@pytest.mark.asyncio
async def test_planner_invalid_json_fallback(caplog):
    client = _make_mock_ollama("This is not JSON: {invalid}")
    planner = BoundedPlanner(client)
    plan = await planner.plan("Do something")
    assert plan == []
    assert any("planner_invalid_json" in record.message for record in caplog.records)


@pytest.mark.asyncio
async def test_planner_unknown_tool_rejection(caplog):
    invalid_tool_json = """[
        {"intent": "hack_pentagon", "parameters": {}}
    ]"""
    client = _make_mock_ollama(invalid_tool_json)
    planner = BoundedPlanner(client)
    plan = await planner.plan("Hack")
    assert plan == []
    assert any("planner_validation_failed" in record.message for record in caplog.records)


@pytest.mark.asyncio
async def test_planner_oversized_plan_rejection(caplog):
    oversized_json = """[
        {"intent": "search_web", "parameters": {"query": "1"}},
        {"intent": "search_web", "parameters": {"query": "2"}},
        {"intent": "search_web", "parameters": {"query": "3"}},
        {"intent": "search_web", "parameters": {"query": "4"}},
        {"intent": "search_web", "parameters": {"query": "5"}},
        {"intent": "search_web", "parameters": {"query": "6"}}
    ]"""
    client = _make_mock_ollama(oversized_json)
    planner = BoundedPlanner(client)
    plan = await planner.plan("Do 6 things")
    assert plan == []
    assert any("planner_validation_failed" in record.message for record in caplog.records)


@pytest.mark.asyncio
async def test_planner_non_list_rejection(caplog):
    dict_json = """{"intent": "search_web", "parameters": {"query": "test"}}"""
    client = _make_mock_ollama(dict_json)
    planner = BoundedPlanner(client)
    plan = await planner.plan("Search")
    assert plan == []
    assert any("planner_validation_failed" in record.message for record in caplog.records)
