import asyncio
import pytest
from unittest.mock import AsyncMock
from core.events.bus import EventBus
from core.events.event_types import EventType
from core.events.models import Event
from core.workflows.workflow_engine import WorkflowEngine, MAX_STEP_OUTPUT_CHARS
from core.workflows.workflow_worker import WorkflowWorker
from core.workflows.recovery import WorkflowRecovery
from core.workflows.state import WorkflowStatus, WorkflowGoal, WorkflowStep
from core.workflows.store import WorkflowStore
from core.tools.tool_worker import ToolWorker


def test_workflow_worker_uses_configured_store_path(monkeypatch, tmp_path):
    from core.workflows.workflow_worker import WorkflowWorker

    store_path = tmp_path / "isolated-workflows.json"
    monkeypatch.setenv("FRIDAY_WORKFLOW_STORE_PATH", str(store_path))

    worker = WorkflowWorker(EventBus())

    assert worker.store.storage_path == str(store_path)


@pytest.mark.asyncio
async def test_tool_chaining_with_bounded_output():
    """Verify Step 2 receives Step 1's bounded output within 1500 chars."""
    bus = EventBus()
    await bus.start()
    engine = WorkflowEngine(bus)
    
    steps = [
        {"intent": "read_text_file", "parameters": {"file_path": "test.txt"}},
        {"intent": "write_text_file", "parameters": {"file_path": "out.txt", "content": "{{step_0_result}}"}}
    ]
    wf_id = await engine.create_workflow("Chain test", steps)
    
    action_requests = []
    async def on_action_req(event):
        action_requests.append(event)
    bus.subscribe(EventType.ACTION_REQUESTED, on_action_req)
    
    await engine.start_workflow(wf_id)
    await bus.drain()
    assert len(action_requests) == 1
    assert action_requests[0].payload["intent"] == "read_text_file"
    
    # Step 1 produces very large output (5000 characters)
    huge_output = "A" * 5000
    await engine.handle_action_result(action_requests[0].correlation_id, success=True, output=huge_output)
    await bus.drain()
    
    # Step 2 should have been triggered with bounded content
    assert len(action_requests) == 2
    step_2_req = action_requests[1]
    assert step_2_req.payload["intent"] == "write_text_file"
    content = step_2_req.payload["parameters"]["content"]
    assert len(content) == MAX_STEP_OUTPUT_CHARS
    assert len(content) <= 1500

    await bus.stop()


@pytest.mark.asyncio
async def test_workflow_terminal_events_keep_originating_correlation_id():
    bus = EventBus()
    await bus.start()
    engine = WorkflowEngine(bus)
    terminal_events = []

    async def capture(event):
        terminal_events.append(event)

    bus.subscribe(EventType.ACTION_GRAPH_COMPLETED, capture)
    bus.subscribe(EventType.RESPONSE_READY, capture)
    workflow_id = await engine.create_workflow(
        "No-op workflow completion probe",
        [],
        correlation_id="source-turn-42",
    )

    await engine.start_workflow(workflow_id)
    await bus.drain()

    assert {event.event_type for event in terminal_events} == {
        EventType.ACTION_GRAPH_COMPLETED,
        EventType.RESPONSE_READY,
    }
    assert {event.correlation_id for event in terminal_events} == {"source-turn-42"}
    await bus.stop()


@pytest.mark.asyncio
async def test_workflow_request_correlation_is_preserved_by_worker(tmp_path):
    bus = EventBus()
    await bus.start()
    worker = WorkflowWorker(bus, store=WorkflowStore(str(tmp_path / "active_workflows.json")))
    request = Event.create(
        EventType.ACTION_GRAPH_STARTED,
        {"goal": "correlation probe", "steps": [{"intent": "search_web", "parameters": {"query": "x"}}]},
        "test",
        "source-turn-43",
    )

    await worker.handle_workflow_request(request)
    workflow = next(iter(worker.engine.active_workflows.values()))
    assert workflow.goal == "correlation probe"
    assert workflow.correlation_id == "source-turn-43"
    await bus.stop()


@pytest.mark.asyncio
async def test_tool_chaining_cumulative_step_budget_across_multiple_references():
    """Verify that multiple {{step_N_result}} references in a step share the MAX_STEP_OUTPUT_CHARS cap cumulatively."""
    bus = EventBus()
    await bus.start()
    engine = WorkflowEngine(bus)

    steps = [
        {"intent": "read_text_file", "parameters": {"file_path": "a.txt"}},
        {"intent": "read_text_file", "parameters": {"file_path": "b.txt"}},
        {
            "intent": "write_text_file",
            "parameters": {
                "file_path": "merged.txt",
                "param_a": "{{step_0_result}}",
                "param_b": "{{step_1_result}}",
            },
        },
    ]
    wf_id = await engine.create_workflow("Multi reference cumulative test", steps)

    action_requests = []
    async def on_action_req(event):
        action_requests.append(event)
    bus.subscribe(EventType.ACTION_REQUESTED, on_action_req)

    await engine.start_workflow(wf_id)
    await bus.drain()

    # Step 0 finishes with 1000 characters
    await engine.handle_action_result(action_requests[0].correlation_id, success=True, output="X" * 1000)
    await bus.drain()

    # Step 1 finishes with 1000 characters
    assert len(action_requests) == 2
    await engine.handle_action_result(action_requests[1].correlation_id, success=True, output="Y" * 1000)
    await bus.drain()

    # Step 2: Cumulative total of param_a and param_b must not exceed MAX_STEP_OUTPUT_CHARS (1400)
    assert len(action_requests) == 3
    step_2_req = action_requests[2]
    param_a = step_2_req.payload["parameters"]["param_a"]
    param_b = step_2_req.payload["parameters"]["param_b"]
    assert len(param_a) == 1000
    assert len(param_b) == 400  # Only 400 characters remaining in cumulative budget
    assert len(param_a) + len(param_b) == MAX_STEP_OUTPUT_CHARS

    await bus.stop()


@pytest.mark.asyncio
async def test_tool_chaining_url_and_json_outputs_share_reduced_budget():
    """URL/JSON-heavy chained results stay within the measured Qwen-safe cap."""
    bus = EventBus()
    await bus.start()
    engine = WorkflowEngine(bus)
    requests = []

    async def on_action_req(event):
        requests.append(event)

    bus.subscribe(EventType.ACTION_REQUESTED, on_action_req)
    workflow_id = await engine.create_workflow("Bound URL and JSON chaining", [
        {"intent": "search_web", "parameters": {"query": "example"}},
        {"intent": "search_web", "parameters": {"query": "second"}},
        {
            "intent": "search_web",
            "parameters": {
                "query": "https://example.com/?first={{step_0_result}}&second={{step_1_result}}",
                "prompt": '{"result":"{{step_0_result}}","source":"{{step_1_result}}"}',
            },
        },
    ])

    await engine.start_workflow(workflow_id)
    await bus.drain()
    await engine.handle_action_result(
        requests[0].correlation_id,
        success=True,
        output='{"url":"https://example.com/one?x=123","answer":"A"}' * 30,
    )
    await bus.drain()
    await engine.handle_action_result(
        requests[1].correlation_id,
        success=True,
        output='https://example.org/two?value=long-value&n=456 ' * 30,
    )
    await bus.drain()

    chained = requests[2].payload["parameters"]
    injected = (
        len(chained["query"].split("first=", 1)[1].split("&second=", 1)[0])
        + len(chained["query"].split("&second=", 1)[1])
        + len(chained["prompt"].split('"result":"', 1)[1].split('","source"', 1)[0])
        + len(chained["prompt"].split('"source":"', 1)[1].split('"}', 1)[0])
    )
    assert injected <= 1400

    await bus.stop()


@pytest.mark.asyncio
async def test_retry_recovery_transient_failure_then_success():
    """Verify transient failure on idempotent tool retries up to max_retries and succeeds."""
    recovery = WorkflowRecovery(max_retries=2, base_backoff_seconds=0.01)
    wf = WorkflowGoal(id="wf1", goal="Search", steps=[
        WorkflowStep(id="wf1_0", intent="search_web", parameters={"query": "BMW"})
    ])
    step = wf.steps[0]
    step.error = "Connection timeout"
    
    # First attempt fails -> retry allowed
    assert recovery.evaluate_failure(wf, step) is True
    recovery.prepare_retry(step)
    assert step.retry_count == 1
    assert step.status == WorkflowStatus.PENDING
    
    # Second attempt fails -> retry allowed
    step.status = WorkflowStatus.RUNNING
    step.error = "Connection timeout again"
    assert recovery.evaluate_failure(wf, step) is True
    recovery.prepare_retry(step)
    assert step.retry_count == 2
    
    # Third attempt fails -> exhausted retries
    step.status = WorkflowStatus.RUNNING
    step.error = "Still down"
    assert recovery.evaluate_failure(wf, step) is False


@pytest.mark.asyncio
async def test_non_idempotent_step_is_never_retried():
    """Verify write, delete, shell, desktop tools are never retried automatically."""
    recovery = WorkflowRecovery(max_retries=2)
    wf = WorkflowGoal(id="wf2", goal="Write file", steps=[
        WorkflowStep(id="wf2_0", intent="write_text_file", parameters={"file_path": "a.txt", "content": "x"})
    ])
    step = wf.steps[0]
    step.error = "Disk write error"
    
    # Must NOT retry
    assert recovery.evaluate_failure(wf, step) is False

    # Also desktop tools
    step.intent = "launch_app"
    assert recovery.evaluate_failure(wf, step) is False
    step.intent = "press_key"
    assert recovery.evaluate_failure(wf, step) is False


@pytest.mark.asyncio
async def test_risk_gating_denial_stops_workflow_cleanly():
    """Verify that user denial on a gated step stops the workflow cleanly."""
    bus = EventBus()
    worker = WorkflowWorker(bus)
    await bus.start()
    await worker.start()
    await asyncio.sleep(0.1)
    
    steps = [
        {"intent": "write_text_file", "parameters": {"file_path": "protected.txt", "content": "data"}}
    ]
    wf_id = await worker.engine.create_workflow("Save data", steps)
    
    failed_events = []
    ready_responses = []

    async def on_fail(e):
        failed_events.append(e)

    async def on_ready(e):
        ready_responses.append(e)

    bus.subscribe(EventType.ACTION_GRAPH_FAILED, on_fail)
    bus.subscribe(EventType.RESPONSE_READY, on_ready)
    
    await worker.engine.start_workflow(wf_id)
    await bus.drain()
    
    # Simulate ACTION_DENIED emitted by ToolWorker
    step_id = f"{wf_id}_0"
    await bus.publish(Event.create(
        EventType.ACTION_DENIED,
        {"reason": "user_refused_permission", "tool_name": "write_text_file"},
        "tool_worker",
        correlation_id=step_id,
    ))
    
    await bus.drain()
    await asyncio.sleep(0.1)
    wf = worker.engine.active_workflows[wf_id]
    assert wf.status == WorkflowStatus.FAILED
    assert len(failed_events) >= 1
    assert any("user_refused" in str(e.payload.get("error", "")) for e in failed_events)
    assert any("Workflow failed at step 'write_text_file'" in r.payload.get("text", "") for r in ready_responses)
    
    await worker.stop()
    await bus.stop()


@pytest.mark.asyncio
async def test_interruption_mid_workflow_cancels_and_drops_late_results():
    """Verify that CONVERSATION_INTERRUPTED cancels the workflow and drops subsequent results."""
    bus = EventBus()
    worker = WorkflowWorker(bus)
    await bus.start()
    await worker.start()
    await asyncio.sleep(0.1)
    
    steps = [
        {"intent": "search_web", "parameters": {"query": "BMW"}},
        {"intent": "write_text_file", "parameters": {"file_path": "a.txt", "content": "{{step_0_result}}"}}
    ]
    wf_id = await worker.engine.create_workflow("Search and save", steps)
    await worker.engine.start_workflow(wf_id)
    await bus.drain()
    
    # User interrupts while step 0 is running
    await bus.publish(Event.create(
        EventType.CONVERSATION_INTERRUPTED,
        {"turn_id": "turn_123", "reason": "interrupted"},
        "orchestrator",
    ))
    await bus.drain()
    await asyncio.sleep(0.1)
    
    wf = worker.engine.active_workflows[wf_id]
    assert wf.status == WorkflowStatus.CANCELLED
    
    # Step 0 late result arrives after interrupt
    step_0_id = f"{wf_id}_0"
    await worker.engine.handle_action_result(step_0_id, success=True, output="BMW M8 top speed is 164 mph")
    await bus.drain()
    
    # Step 1 must NOT be started
    step_1 = wf.steps[1]
    assert step_1.status == WorkflowStatus.CANCELLED
    
    await worker.stop()
    await bus.stop()


@pytest.mark.asyncio
async def test_e2e_search_and_remember_workflow():
    """End-to-end workflow: Search web for BMW M8 top speed and remember it."""
    bus = EventBus()
    worker = WorkflowWorker(bus)
    await bus.start()
    await worker.start()
    await asyncio.sleep(0.1)
    
    completed_events = []
    progress_events = []
    responses = []
    
    async def on_completed(e):
        completed_events.append(e)

    async def on_progress(e):
        progress_events.append(e)

    async def on_resp(e):
        responses.append(e)

    bus.subscribe(EventType.ACTION_GRAPH_COMPLETED, on_completed)
    bus.subscribe(EventType.ASSISTANT_RESPONSE_PARTIAL, on_progress)
    bus.subscribe(EventType.RESPONSE_READY, on_resp)
    
    # Step 1: search_web, Step 2: write_text_file (simulating recording/saving fact)
    steps = [
        {"intent": "search_web", "parameters": {"query": "BMW M8 top speed"}},
        {"intent": "write_text_file", "parameters": {"file_path": "memory.txt", "content": "{{step_0_result}}"}}
    ]
    
    # Initiate via ACTION_GRAPH_STARTED
    await bus.publish(Event.create(
        EventType.ACTION_GRAPH_STARTED,
        {"goal": "Search BMW M8 and remember it", "steps": steps},
        "orchestrator",
    ))
    
    await bus.drain()
    await asyncio.sleep(0.1)
    
    # Find the newly created workflow
    wf = next(w for w in worker.engine.active_workflows.values() if w.goal == "Search BMW M8 and remember it")
    
    # Step 1 running
    assert wf.steps[0].status == WorkflowStatus.RUNNING
    # Complete step 1
    await bus.publish(Event.create(
        EventType.ACTION_COMPLETED,
        {"tool_name": "search_web", "success": True, "output": "164 mph"},
        "tool_worker",
        correlation_id=f"{wf.id}_0",
    ))
    await bus.drain()
    await asyncio.sleep(0.1)
    
    # Step 2 running with resolved parameter
    assert wf.steps[1].status == WorkflowStatus.RUNNING
    assert wf.steps[1].parameters["content"] == "164 mph"
    
    # Complete step 2
    await bus.publish(Event.create(
        EventType.ACTION_COMPLETED,
        {"tool_name": "write_text_file", "success": True, "output": "Saved"},
        "tool_worker",
        correlation_id=f"{wf.id}_1",
    ))
    await bus.drain()
    await asyncio.sleep(0.1)
    
    # Workflow completed: returns grounded result
    assert wf.status == WorkflowStatus.COMPLETED
    assert len(completed_events) == 1
    assert any("completed successfully" in r.payload.get("text", "") for r in responses)
    assert any("Step 1/2" in p.payload.get("text", "") for p in progress_events)
    
    await worker.stop()
    await bus.stop()


@pytest.mark.asyncio
async def test_orchestrator_e2e_search_and_remember_workflow(monkeypatch, tmp_path):
    """Orchestrator-level test for 'search the web for X and remember the answer' with LLM and search mocked."""
    from core.memory.memory_worker import MemoryWorker
    from core.orchestrator.conversation import OrchestratorWorker
    from core.router.intent_router import IntentRouter
    from core.router.llm_fallback import LlmFallbackRouter
    from core.llm.streaming_worker import StreamingLlmWorker
    from core.llm.stream_aggregator import ResponseAggregator
    from core.workflows.prompt_planner import PromptPlanner
    from types import SimpleNamespace

    bus = EventBus()
    await bus.start()

    memory_worker = MemoryWorker(bus, db_path=str(tmp_path / "memory.sqlite"))
    tool_worker = ToolWorker(bus)
    workflow_worker = WorkflowWorker(bus)
    await memory_worker.start()
    await tool_worker.start()
    await workflow_worker.start()

    # Mock Planner LLM
    class FakePlannerClient:
        async def generate(self, prompt: str, **kwargs):
            metrics = SimpleNamespace(success=True)
            res = (
                '[\n'
                '  {"intent": "search_web", "parameters": {"query": "BMW M8 top speed"}},\n'
                '  {"intent": "remember", "parameters": {"fact": "{{step_0_result}}"}}\n'
                ']'
            )
            return res, metrics

    class FakeStreamingClient:
        model = "test-model"
        async def stream_generate(self, prompt: str):
            yield "Done.", True

    planner_client = FakePlannerClient()
    prompt_planner = PromptPlanner(planner_client, tool_registry=tool_worker.registry)

    streaming_client = FakeStreamingClient()
    streaming_worker = StreamingLlmWorker(
        bus,
        streaming_client,
        ResponseAggregator(bus),
        timeout_seconds=5,
    )
    llm_router = LlmFallbackRouter(
        ollama_client=SimpleNamespace(model="test-model"),
        event_bus=bus,
        streaming_worker=streaming_worker,
    )
    router = IntentRouter(bus, llm_router)
    orchestrator = OrchestratorWorker(
        bus,
        router,
        streaming_worker,
        prompt_planner=prompt_planner,
    )

    # Mock search_web in BrowserTools to return instant answer
    from core.tools.tool_models import ToolResult
    async def mock_search_web(query: str) -> ToolResult:
        return ToolResult(True, "The BMW M8 top speed is 190 mph with M Driver package.")
    tool_worker.registry.register("search_web", mock_search_web)

    responses: list[str] = []
    memory_writes: list[Event] = []
    completed_graphs: list[Event] = []

    async def on_resp(e: Event):
        responses.append(e.payload.get("text", ""))

    async def on_mem_write(e: Event):
        memory_writes.append(e)

    async def on_graph_completed(e: Event):
        completed_graphs.append(e)

    bus.subscribe(EventType.RESPONSE_READY, on_resp)
    bus.subscribe(EventType.MEMORY_WRITE_REQUEST, on_mem_write)
    bus.subscribe(EventType.ACTION_GRAPH_COMPLETED, on_graph_completed)

    orchestrator_task = asyncio.create_task(orchestrator.run())
    await asyncio.sleep(0.05)

    try:
        # User triggers workflow via conversation orchestrator
        await bus.publish(Event.create(
            EventType.USER_TEXT_RECEIVED,
            {"text": "Search the web for BMW M8 top speed and remember the answer"},
            "test_user",
        ))

        # Wait for workflow completion
        for _ in range(50):
            if completed_graphs:
                break
            await asyncio.sleep(0.1)

        await bus.drain()
        await asyncio.sleep(0.1)

        # 1. Action graph completed successfully
        assert len(completed_graphs) == 1
        assert completed_graphs[0].payload["success"] is True

        # 2. Result message returned to user: answer plus 'Saved to memory.'
        assert any("190 mph" in r and "Saved to memory" in r for r in responses)

        # 3. Remember step published MEMORY_WRITE_REQUEST with explicit_user_approved=True
        assert len(memory_writes) >= 1
        assert memory_writes[0].payload["explicit_user_approved"] is True
        assert "190 mph" in memory_writes[0].payload["content"]

    finally:
        await orchestrator.stop()
        await orchestrator_task
        await workflow_worker.stop()
        await tool_worker.stop()
        await memory_worker.stop()
        await bus.stop()
