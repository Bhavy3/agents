"""Regressions from the ten real search failures, plus adjacent boundaries."""
from types import SimpleNamespace
from unittest.mock import AsyncMock
import asyncio
import httpx

import pytest

from core.orchestrator import web_search
from core.orchestrator.web_search import ground_web_answer, WEB_ANSWER_NOT_FOUND
from core.tools.page_reader import extract_relevant_text
from core.tools import browser_tools
from core.tools import page_reader
from core.orchestrator.web_search import resolve_citations, balanced_evidence, PendingWebSearch
from core.orchestrator.conversation import OrchestratorWorker
from core.events.bus import EventBus
from core.events.event_types import EventType


@pytest.mark.parametrize("evidence", ["High 96 degrees, low 75 degrees.", "High 96°F, low 75°F."])
def test_unknown_or_fahrenheit_units_cannot_be_relabelled_celsius(evidence):
    assert ground_web_answer("High 96°C, low 75°C.", evidence) == WEB_ANSWER_NOT_FOUND


def test_number_inside_decimal_is_not_evidence():
    assert ground_web_answer("There are 15 items.", "Version 3.15 is available.") == WEB_ANSWER_NOT_FOUND


def test_citation_must_be_exact_not_a_source_url_prefix():
    assert ground_web_answer(
        "See https://example.com/", "1. Page\nSource: https://example.com/product\nDetails."
    ) == WEB_ANSWER_NOT_FOUND


def test_navigation_does_not_displace_article_evidence():
    page = "<nav>" + "ASUS GPU gaming menu store account " * 100 + "</nav>"
    page += "<main><h1>GPU comparison</h1><p>The ASUS model has 16GB memory and handles 1440p gaming.</p></main>"
    result = extract_relevant_text(page, "ASUS GPU 1440p gaming", max_chars=300)
    assert "16GB" in result
    assert "menu" not in result


@pytest.mark.asyncio
async def test_no_results_is_not_reported_as_offline(monkeypatch):
    class EmptySearch:
        def __init__(self, **kwargs):
            pass

        def text(self, *args, **kwargs):
            raise RuntimeError("No results found.")

    monkeypatch.setattr(browser_tools, "DDGS", EmptySearch)
    result = await browser_tools.BrowserTools().search_web("unfindable subject")
    assert result.error == "no_results"
    assert "couldn't reach" not in result.output


@pytest.mark.asyncio
async def test_query_preserves_late_constraints_after_deduplication(monkeypatch):
    sent = []

    class CaptureSearch:
        def __init__(self, **kwargs):
            pass

        def text(self, query, **kwargs):
            sent.append(query)
            return [{"title": "Laptop", "body": "Laptop budget comparison."}]

    monkeypatch.setattr(browser_tools, "DDGS", CaptureSearch)
    query = "Compare laptops. " + "Consider keyboard screen battery and ports. " * 20
    query += "Budget below Rs 25000 in India; no refurbished products."
    await browser_tools.BrowserTools().search_web(query)
    assert "25000" in sent[0]
    assert "India" in sent[0]
    assert "refurbished" in sent[0]
    assert len(sent[0]) <= 500


def test_numbered_citations_expand_only_existing_source_ids():
    evidence = "1. Fact\nSource: https://example.com/fact\nEvidence: 42 items."
    answer = resolve_citations("There are 42 items [1].", evidence)
    assert ground_web_answer(answer, evidence) != WEB_ANSWER_NOT_FOUND
    assert ground_web_answer(resolve_citations("There are 42 items [9].", evidence), evidence) == WEB_ANSWER_NOT_FOUND


def test_grouped_citations_and_query_date_are_not_false_failures():
    evidence = "1. Release\nSource: https://example.com/release\nEvidence: Version 3.15.1 is the stable release."
    answer = resolve_citations("The stable version as of 23 October 2026 is 3.15.1 (1).", evidence)
    assert ground_web_answer(answer, evidence, query="stable version as of 23 October 2026") != WEB_ANSWER_NOT_FOUND


def test_uncertainty_can_name_the_requested_nonexistent_model():
    evidence = "1. Products\nSource: https://example.com/products\nEvidence: Model 5000."
    answer = resolve_citations("I couldn't find verified specifications for the requested model 9090 [1].", evidence)
    assert ground_web_answer(answer, evidence, query="model 9090 specifications") != WEB_ANSWER_NOT_FOUND


def test_snippet_price_is_not_a_verified_current_price():
    evidence = "1. Listing\nSource: https://example.com/listing\nEvidence kind: search snippet (page not verified)\nEvidence: Product price Rs 999."
    answer = resolve_citations("The current price is Rs 999 [1].", evidence)
    assert ground_web_answer(answer, evidence, query="current product price") == WEB_ANSWER_NOT_FOUND


def test_currency_cannot_be_changed():
    assert ground_web_answer("The cost is $999.", "The cost is Rs 999.") == WEB_ANSWER_NOT_FOUND


@pytest.mark.asyncio
async def test_invalid_planner_output_falls_back_without_invented_queries(monkeypatch):
    client = SimpleNamespace(generate=AsyncMock(return_value=("not JSON", SimpleNamespace(success=True))))
    tools = browser_tools.BrowserTools(query_client=client)
    search = AsyncMock(return_value=[{"title": "Fact", "href": "https://example.com", "body": "Fact."}])
    monkeypatch.setattr(tools, "_search_records", search)
    result = await tools.search_web("a factual question")
    assert result.success
    assert search.await_count == 1
    assert search.call_args.args == ("a factual question",)


@pytest.mark.asyncio
async def test_official_domain_filter_does_not_accept_lookalike_host(monkeypatch):
    tools = browser_tools.BrowserTools()
    search = AsyncMock(return_value=[
        {"title": "Wrong", "href": "https://evilnasa.gov/story", "body": "NASA"},
        {"title": "Right", "href": "https://science.nasa.gov/story", "body": "NASA"},
    ])
    monkeypatch.setattr(tools, "_search_records", search)
    result = await tools.search_web("Use nasa.gov for official evidence")
    assert "science.nasa.gov" in result.output
    assert "evilnasa.gov" not in result.output


def test_evidence_budget_keeps_later_sources():
    evidence = "\n".join(f"{i}. Page\nSource: https://example.com/{i}\nEvidence: " + "detail " * 500 for i in range(1, 4))
    packed = balanced_evidence(evidence, 1500)
    assert len(packed) <= 1500
    for i in range(1, 4):
        assert f"https://example.com/{i}" in packed


@pytest.mark.asyncio
async def test_oversized_stream_is_stopped_before_full_download(monkeypatch):
    class LargeStream(httpx.AsyncByteStream):
        read = 0
        closed = False

        async def __aiter__(self):
            for _ in range(300):
                self.read += 1
                yield b"x" * 100000

        async def aclose(self):
            self.closed = True

    stream = LargeStream()
    transport = httpx.MockTransport(lambda request: httpx.Response(200, stream=stream))
    client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: client(transport=transport, **kw))
    assert await page_reader.fetch_page("https://example.com/large") is None
    assert stream.read == 21
    assert stream.closed


@pytest.mark.asyncio
async def test_slow_drip_has_total_deadline(monkeypatch):
    class EndlessStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            while True:
                await asyncio.sleep(0.005)
                yield b"x"

    transport = httpx.MockTransport(lambda request: httpx.Response(200, stream=EndlessStream()))
    client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: client(transport=transport, **kw))
    monkeypatch.setattr(page_reader, "PAGE_FETCH_TIMEOUT_SECONDS", 0.04)
    assert await asyncio.wait_for(page_reader.fetch_page("https://example.com/drip"), 0.5) is None


@pytest.mark.asyncio
async def test_bad_draft_is_repaired_before_publication():
    bus = EventBus()
    await bus.start()
    worker = SimpleNamespace(generate_buffered=AsyncMock(side_effect=[
        "The high is 96°C [1].",
        "The forecast reports a 0% precipitation chance; temperature units are not specified [1].",
    ]), cancel_all=lambda: None)
    app = OrchestratorWorker(bus, None, worker)
    pending = PendingWebSearch("weather celsius", "weather celsius", "turn", "", "")
    app.active_turn_id = "turn"
    app._pending_web_searches["case"] = pending
    responses = []

    async def record(event):
        responses.append(event.payload["text"])

    bus.subscribe(EventType.RESPONSE_READY, record)
    try:
        await app._generate_web_search_answer("case", pending,
            "1. Forecast\nSource: https://example.com/weather\nEvidence: High 96 degrees. Precipitation chance 0%.")
        await bus.drain()
        assert worker.generate_buffered.await_count == 2
        assert len(responses) == 1
        assert "96°C" not in responses[0]
        assert "0%" in responses[0]
        assert "https://example.com/weather" in responses[0]
    finally:
        await app.stop()
        await bus.stop()


@pytest.mark.asyncio
async def test_interruption_during_buffered_generation_prevents_late_answer():
    bus = EventBus()
    await bus.start()
    entered, release = asyncio.Event(), asyncio.Event()

    async def generate(*args, **kwargs):
        entered.set()
        await release.wait()
        return "Paris is the capital of France."

    app = OrchestratorWorker(bus, None, SimpleNamespace(generate_buffered=generate, cancel_all=lambda: None))
    pending = PendingWebSearch("capital", "capital", "old", "", "")
    app.active_turn_id = "old"
    app._pending_web_searches["old-case"] = pending
    responses = []

    async def record(event):
        responses.append(event)

    bus.subscribe(EventType.RESPONSE_READY, record)
    task = asyncio.create_task(app._generate_web_search_answer("old-case", pending, "Paris is the capital of France."))
    try:
        await asyncio.wait_for(entered.wait(), 1)
        app._pending_web_searches.pop("old-case")
        app.active_turn_id = "new"
        release.set()
        await task
        await bus.drain()
        assert not responses
    finally:
        release.set()
        await app.stop()
        await bus.stop()


@pytest.mark.asyncio
async def test_slow_web_answer_uses_evidence_fallback_within_answer_budget(monkeypatch):
    bus = EventBus()
    await bus.start()

    async def slow_generate(*args, **kwargs):
        await asyncio.sleep(0.2)
        return "slow draft"

    worker = SimpleNamespace(generate_buffered=slow_generate, cancel_all=lambda: None)
    app = OrchestratorWorker(bus, None, worker)
    pending = PendingWebSearch("weather", "weather", "slow-turn", "", "")
    app.active_turn_id = "slow-turn"
    app._pending_web_searches["slow-case"] = pending
    monkeypatch.setattr(web_search, "WEB_ANSWER_GENERATION_TIMEOUT_SECONDS", 0.02)

    responses = []

    async def record(event):
        responses.append(event.payload["text"])

    bus.subscribe(EventType.RESPONSE_READY, record)
    try:
        await asyncio.wait_for(
            app._generate_web_search_answer(
                "slow-case",
                pending,
                "1. Forecast\nSource: https://example.com/weather\nEvidence: Rain is possible.",
            ),
            0.5,
        )
        await bus.drain()
        assert len(responses) == 1
        assert "https://example.com/weather" in responses[0]
    finally:
        await app.stop()
        await bus.stop()


@pytest.mark.asyncio
async def test_orchestrator_stop_cancels_background_web_answer_tasks():
    bus = EventBus()
    await bus.start()
    worker = SimpleNamespace(generate_buffered=AsyncMock(), cancel_all=lambda: None)
    app = OrchestratorWorker(bus, None, worker)
    started = asyncio.Event()

    async def never_finishes():
        started.set()
        await asyncio.Event().wait()

    task = asyncio.create_task(never_finishes())
    app._web_search_answer_tasks["cancel-me"] = task
    await started.wait()
    await app.stop()
    assert task.cancelled()
    await bus.stop()
