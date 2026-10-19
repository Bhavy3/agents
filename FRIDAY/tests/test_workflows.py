import asyncio
import pytest
from core.events.bus import EventBus
from core.events.event_types import EventType
from core.events.models import Event
from core.workflows.workflow_engine import WorkflowEngine
from core.workflows.state import WorkflowStatus


@pytest.mark.asyncio
async def test_workflow_engine_sequential_execution():
    bus = EventBus()
    engine = WorkflowEngine(bus)
    
    steps = [
        {"intent": "test_1", "parameters": {"p": 1}},
        {"intent": "test_2", "parameters": {"p": 2}}
    ]
    
    workflow_id = await engine.create_workflow("multi-step test", steps)
    await bus.start()
    
    # 1. Start workflow
    await engine.start_workflow(workflow_id)
    workflow = engine.active_workflows[workflow_id]
    
    assert workflow.status == WorkflowStatus.RUNNING
    assert workflow.steps[0].status == WorkflowStatus.RUNNING
    
    # 2. Complete first step
    await engine.handle_action_result(workflow.steps[0].id, success=True, output="first done")
    assert workflow.steps[0].status == WorkflowStatus.COMPLETED
    assert workflow.steps[1].status == WorkflowStatus.RUNNING
    
    # 3. Complete second step
    await engine.handle_action_result(workflow.steps[1].id, success=True, output="second done")
    assert workflow.steps[1].status == WorkflowStatus.COMPLETED
    assert workflow.status == WorkflowStatus.COMPLETED
    
    await bus.stop()


@pytest.mark.asyncio
async def test_workflow_recovery_retries():
    from core.workflows.workflow_worker import WorkflowWorker
    bus = EventBus()
    worker = WorkflowWorker(bus)
    
    steps = [{"intent": "search_web", "parameters": {"query": "test"}}]
    workflow_id = await worker.engine.create_workflow("retry test", steps)
    workflow = worker.engine.active_workflows[workflow_id]
    
    await bus.start()
    await worker.start()
    await asyncio.sleep(0.1) # Wait for subscription to settle
    
    # Trigger first failure
    step_id = workflow.steps[0].id
    await bus.publish(Event.create(
        EventType.ACTION_FAILED, 
        {"error": "temporary failure"}, 
        "test", 
        correlation_id=step_id
    ))
    
    # Wait for recovery/retry logic
    await asyncio.sleep(1.2)
    
    assert workflow.steps[0].retry_count == 1
    assert workflow.steps[0].status == WorkflowStatus.RUNNING # Should have retried
    
    await worker.stop()
    await bus.stop()


@pytest.mark.asyncio
async def test_workflow_step_limit():
    bus = EventBus()
    engine = WorkflowEngine(bus)
    
    # 6 steps exceeds limit
    steps = [{"intent": "t", "parameters": {}}] * 6
    
    with pytest.raises(ValueError):
        await engine.create_workflow("overload", steps)


@pytest.mark.asyncio
async def test_duplicate_action_result_does_not_advance_workflow_twice():
    bus = EventBus()
    engine = WorkflowEngine(bus)
    workflow_id = await engine.create_workflow("duplicate result", [
        {"intent": "first", "parameters": {}},
        {"intent": "second", "parameters": {}},
    ])
    await bus.start()
    await engine.start_workflow(workflow_id)
    workflow = engine.active_workflows[workflow_id]
    first_step = workflow.steps[0]

    await engine.handle_action_result(first_step.id, True, "done")
    assert workflow.steps[1].status == WorkflowStatus.RUNNING

    # A duplicate completion for the already-completed first step is ignored.
    await engine.handle_action_result(first_step.id, True, "duplicate")
    assert workflow.steps[1].status == WorkflowStatus.RUNNING
    assert workflow.status == WorkflowStatus.RUNNING

    await bus.stop()


@pytest.mark.asyncio
async def test_search_then_remember_keeps_a_concise_grounded_fact():
    bus = EventBus()
    engine = WorkflowEngine(bus)
    action_requests = []
    responses = []

    async def capture_action(event):
        action_requests.append(event)

    async def capture_response(event):
        responses.append(event)

    bus.subscribe(EventType.ACTION_REQUESTED, capture_action)
    bus.subscribe(EventType.RESPONSE_READY, capture_response)
    await bus.start()

    workflow_id = await engine.create_workflow(
        "First search for the capital of France, then remember it.",
        [
            {"intent": "search_web", "parameters": {"query": "capital of France"}},
            {"intent": "remember", "parameters": {"fact": ""}},
        ],
    )
    await engine.start_workflow(workflow_id)
    workflow = engine.active_workflows[workflow_id]
    raw_search_result = (
        "1. Capital of France\n"
        "This is a chronological list of capitals of France. "
        "The capital of France has been Paris since its liberation in 1944.\n"
        "4. Capital of France - Simple English Wikipedia\n"
        "The capital of France is Paris."
    )

    await engine.handle_action_result(workflow.steps[0].id, True, raw_search_result)
    await bus.drain()

    assert action_requests[1].payload["parameters"]["fact"] == "The capital of France is Paris."

    await engine.handle_action_result(workflow.steps[1].id, True, "Remembered: The capital of France is Paris.")
    await bus.drain()

    assert responses[-1].payload["text"] == "The capital of France is Paris. Saved to memory."
    await bus.stop()
