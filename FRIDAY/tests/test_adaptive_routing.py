import asyncio
from unittest.mock import AsyncMock, MagicMock
import pytest

from core.llm.llm_worker import LlmWorker
from core.router.adaptive_router import AdaptiveRouter
from core.router.latency_predictor import estimate_latency, infer_latency_budget


@pytest.mark.asyncio
async def test_router_simple_query_uses_3b():
    """Simple queries use 3B."""
    router = AdaptiveRouter()
    model, reason = await router.decide_model("weather?")
    assert model == "3b"
    assert reason == "simple_query"


@pytest.mark.asyncio
async def test_router_complex_query_uses_7b():
    """Complex queries with patience use 7B."""
    router = AdaptiveRouter()
    model, reason = await router.decide_model("analyze the trends")
    assert model == "7b"
    assert reason == "complex_query_needs_7b"


@pytest.mark.asyncio
async def test_router_urgent_complex_uses_3b():
    """Complex queries with urgency trade off accuracy for speed using 3B."""
    router = AdaptiveRouter()
    model, reason = await router.decide_model("quick analysis")
    assert model == "3b"
    assert reason == "complex_query_urgent_use_3b_fast"


@pytest.mark.asyncio
async def test_router_long_complex_request_avoids_excessive_7b_wait():
    manager = MagicMock()
    manager.current_model = "3b"
    manager.model_processes = {"3b": object(), "7b": None}
    router = AdaptiveRouter(model_manager=manager)
    query = "Find a verified non-stop route from one city to another tomorrow under a strict budget, including schedule, baggage, and bookable fare details, and report every missing constraint without inventing anything."
    model, reason = await router.decide_model(query)
    assert model == "3b"
    assert reason == "complex_query_exceeds_interactive_cap_use_3b_fast"


@pytest.mark.asyncio
async def test_router_does_not_trust_stale_7b_process_without_health_readiness():
    manager = MagicMock()
    manager.current_model = "3b"
    manager.model_processes = {"3b": object(), "7b": object()}
    manager.model_ready = {"3b": True, "7b": False}
    router = AdaptiveRouter(model_manager=manager)
    query = "Compare mirrorless cameras under EUR 900 with 4K video and a weather-sealed body; preserve every constraint."

    model, reason = await router.decide_model(query)

    assert model == "3b"
    assert reason == "complex_query_exceeds_interactive_cap_use_3b_fast"


@pytest.mark.asyncio
async def test_router_avoids_expensive_7b_when_gpu_offload_is_disabled():
    manager = MagicMock()
    manager.current_model = "3b"
    manager.model_processes = {"3b": object(), "7b": object()}
    manager.model_ready = {"3b": True, "7b": True}
    manager.model_gpu_layers = {"3b": 33, "7b": 0}
    router = AdaptiveRouter(model_manager=manager)
    query = "Compare three database indexing strategies and explain their trade-offs in detail."

    model, reason = await router.decide_model(query)

    assert model == "3b"
    assert reason == "complex_query_exceeds_interactive_cap_use_3b_fast"


def test_latency_budget_inference_urgent():
    """Urgent keywords set low latency budget."""
    assert infer_latency_budget("do this asap") == 2.0
    assert infer_latency_budget("tell me quick") == 2.0
    assert infer_latency_budget("answer now") == 2.0


def test_latency_budget_inference_patient():
    """Deep analysis keywords set high latency budget."""
    assert infer_latency_budget("deeply analyze this codebase") == 20.0
    assert infer_latency_budget("give me a comprehensive summary") == 18.0
    assert infer_latency_budget("thoroughly review") == 20.0


def test_latency_predictor_3b_fast():
    """3B predicted latency is strictly lower than 7B predicted latency."""
    lat_3b = estimate_latency("hello", "3b")
    lat_7b = estimate_latency("hello", "7b")
    assert lat_3b < lat_7b
    assert lat_3b > 0.0


@pytest.mark.asyncio
async def test_routing_respects_budget():
    """Complex query with a strict 2s budget chooses 3B with tradeoff reason."""
    router = AdaptiveRouter()
    model, reason = await router.decide_model("design an architecture right now")
    assert model == "3b"
    assert reason == "complex_query_urgent_use_3b_fast"


@pytest.mark.asyncio
async def test_route_reports_active_fallback_when_model_switch_fails(caplog):
    """A failed model switch must not be reported as an executed route."""
    import logging

    caplog.set_level(logging.INFO, logger="core.router.adaptive_router")
    mock_mm = MagicMock()
    mock_mm.current_model = "3b"
    mock_mm.switch_model = AsyncMock(return_value=False)
    router = AdaptiveRouter(model_manager=mock_mm)

    model, reason = await router.route("analyze the trends")

    assert mock_mm.switch_model.await_count == 1
    assert model == "3b"
    assert reason == "complex_query_needs_7b; switch_failed_fallback_3b"
    assert "routing_executed: model=3b" in caplog.text


@pytest.mark.asyncio
async def test_route_does_not_report_target_when_switch_result_is_not_applied(caplog):
    """The backend's active model, rather than a switch return value, is authoritative."""
    import logging

    caplog.set_level(logging.INFO, logger="core.router.adaptive_router")
    mock_mm = MagicMock()
    mock_mm.current_model = "3b"
    mock_mm.switch_model = AsyncMock(return_value=True)
    router = AdaptiveRouter(model_manager=mock_mm)

    model, reason = await router.route("analyze the trends")

    assert model == "3b"
    assert reason == "complex_query_needs_7b; switch_failed_fallback_3b"
    assert "routing_executed: model=3b" in caplog.text


@pytest.mark.asyncio
async def test_route_without_manager_logs_selection_not_model_execution(caplog):
    """A logical route choice alone does not prove the backend changed models."""
    import logging

    caplog.set_level(logging.INFO, logger="core.router.adaptive_router")
    router = AdaptiveRouter()

    model, reason = await router.route("analyze the trends")

    assert model == "7b"
    assert reason == "complex_query_needs_7b"
    assert "routing_selected: model=7b" in caplog.text
    assert "routing_executed:" not in caplog.text


@pytest.mark.asyncio
async def test_fallback_on_timeout():
    """When 3B inference times out, automatically escalates to 7B and retries."""
    mock_client = MagicMock()
    mock_mm = MagicMock()
    mock_mm.current_model = "3b"
    mock_mm.switch_model = AsyncMock()

    call_count = 0
    async def delayed_generate(prompt, max_tokens=500):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            await asyncio.sleep(15)  # artificially delay
            return "delayed"
        return "7b response"

    mock_client.generate = delayed_generate

    worker = LlmWorker(
        client=mock_client,
        model_manager=mock_mm,
        timeout=0.05,
        fallback_reason="timeout_escalation",
    )
    response = await worker.generate("complex question")

    mock_mm.switch_model.assert_awaited_once_with("7b", "timeout_escalation")
    assert response == "7b response"


@pytest.mark.asyncio
async def test_metrics_and_decision_log_20_queries(caplog):
    """Test 20 diverse queries and log routing decisions with consistency check."""
    import logging
    caplog.set_level(logging.INFO)
    router = AdaptiveRouter()

    test_queries = [
        ("weather", "simple"),
        ("analyze deeply", "complex"),
        ("quick fix", "simple"),
        ("comprehensive research", "complex"),
        ("what time is it", "simple"),
        ("tell me a joke", "simple"),
        ("how are you doing", "medium"),
        ("thanks a lot", "simple"),
        ("deep dive into transformers", "complex"),
        ("explain quantum mechanics thoroughly", "complex"),
        ("quick explanation of git", "complex"),
        ("code a sorting algorithm asap", "complex"),
        ("build a full stack application in detail", "complex"),
        ("hi there", "simple"),
        ("is it raining", "medium"),
        ("make me a coffee app right now", "complex"),
        ("analyze market trends with patience", "complex"),
        ("cool, nice job", "simple"),
        ("design microservices architecture", "complex"),
        ("fast answer on database indexes", "complex"),
    ]

    results = []
    for query, expected_complexity in test_queries:
        actual_model, reason = await router.decide_model(query)
        assert actual_model in ("3b", "7b")
        results.append((query, actual_model, reason))
        logging.getLogger("core.router.adaptive_router").info(
            f"query='{query}' -> model={actual_model} reason={reason}"
        )

    assert len(results) == 20
