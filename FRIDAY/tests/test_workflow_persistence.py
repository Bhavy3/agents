import pytest

from core.events.bus import EventBus
from core.events.event_types import EventType
from core.workflows.state import WorkflowGoal, WorkflowStatus, WorkflowStep
from core.workflows.store import WorkflowStore
from core.workflows.workflow_worker import WorkflowWorker


async def _worker_for(tmp_path, workflow: WorkflowGoal):
    store = WorkflowStore(str(tmp_path / "active_workflows.json"))
    store.save_workflows({workflow.id: workflow})
    bus = EventBus()
    worker = WorkflowWorker(bus, store=store)
    await bus.start()
    return bus, worker


@pytest.mark.asyncio
async def test_persisted_running_workflow_resumes_pending_step(tmp_path):
    workflow = WorkflowGoal(
        id="resume01",
        goal="Resume pending work",
        status=WorkflowStatus.RUNNING,
        steps=[
            WorkflowStep("resume01_0", "read_text_file", {"file_path": "done.txt"}, WorkflowStatus.COMPLETED, "done"),
            WorkflowStep("resume01_1", "search_web", {"query": "FRIDAY"}),
        ],
    )
    bus, worker = await _worker_for(tmp_path, workflow)
    requested = []
    async def on_requested(event):
        requested.append(event)
    bus.subscribe(EventType.ACTION_REQUESTED, on_requested)

    await worker.resume_persisted_workflows()
    await bus.drain()

    resumed = worker.engine.active_workflows[workflow.id]
    assert resumed.steps[0].status == WorkflowStatus.COMPLETED
    assert resumed.steps[0].result == "done"
    assert resumed.steps[1].status == WorkflowStatus.RUNNING
    assert [event.correlation_id for event in requested] == ["resume01_1"]
    assert requested[0].payload["intent"] == "search_web"

    await bus.stop()


@pytest.mark.asyncio
async def test_persisted_waiting_confirmation_is_preserved_without_replay(tmp_path):
    workflow = WorkflowGoal(
        id="wait0001",
        goal="Wait for approval",
        status=WorkflowStatus.WAITING_CONFIRMATION,
        steps=[
            WorkflowStep(
                "wait0001_0",
                "write_text_file",
                {"file_path": "protected.txt", "content": "x"},
                WorkflowStatus.WAITING_CONFIRMATION,
            ),
            WorkflowStep("wait0001_1", "search_web", {"query": "later"}),
        ],
    )
    bus, worker = await _worker_for(tmp_path, workflow)
    requested = []
    async def on_requested(event):
        requested.append(event)
    bus.subscribe(EventType.ACTION_REQUESTED, on_requested)

    await worker.resume_persisted_workflows()
    await bus.drain()

    resumed = worker.engine.active_workflows[workflow.id]
    assert resumed.status == WorkflowStatus.WAITING_CONFIRMATION
    assert resumed.steps[0].status == WorkflowStatus.WAITING_CONFIRMATION
    assert resumed.steps[1].status == WorkflowStatus.PENDING
    assert requested == []

    await bus.stop()


@pytest.mark.asyncio
async def test_completed_steps_are_not_rerun_or_requested_twice(tmp_path):
    workflow = WorkflowGoal(
        id="done0001",
        goal="Continue after completed work",
        status=WorkflowStatus.RUNNING,
        steps=[
            WorkflowStep("done0001_0", "search_web", {"query": "already"}, WorkflowStatus.COMPLETED, "cached answer"),
            WorkflowStep("done0001_1", "read_text_file", {"file_path": "next.txt"}),
        ],
    )
    bus, worker = await _worker_for(tmp_path, workflow)
    requested = []
    async def on_requested(event):
        requested.append(event)
    bus.subscribe(EventType.ACTION_REQUESTED, on_requested)

    await worker.resume_persisted_workflows()
    # A second recovery call is a no-op and cannot duplicate the request.
    await worker.resume_persisted_workflows()
    await bus.drain()

    resumed = worker.engine.active_workflows[workflow.id]
    assert resumed.steps[0].status == WorkflowStatus.COMPLETED
    assert resumed.steps[0].result == "cached answer"
    assert resumed.steps[1].status == WorkflowStatus.RUNNING
    assert len(requested) == 1
    assert requested[0].correlation_id == "done0001_1"

    await bus.stop()


@pytest.mark.asyncio
async def test_non_idempotent_in_flight_step_fails_conservatively(tmp_path):
    workflow = WorkflowGoal(
        id="unsafe01",
        goal="Do not duplicate a write",
        status=WorkflowStatus.RUNNING,
        steps=[
            # The persisted model records RUNNING but not whether the request
            # was delivered or acknowledged.  Replaying a write is unsafe.
            WorkflowStep(
                "unsafe01_0",
                "write_text_file",
                {"file_path": "important.txt", "content": "once"},
                WorkflowStatus.RUNNING,
            ),
        ],
    )
    bus, worker = await _worker_for(tmp_path, workflow)
    failures = []
    requested = []
    async def on_failure(event):
        failures.append(event)
    async def on_requested(event):
        requested.append(event)
    bus.subscribe(EventType.ACTION_GRAPH_FAILED, on_failure)
    bus.subscribe(EventType.ACTION_REQUESTED, on_requested)

    await worker.resume_persisted_workflows()
    await bus.drain()

    resumed = worker.engine.active_workflows[workflow.id]
    assert resumed.status == WorkflowStatus.FAILED
    assert resumed.steps[0].status == WorkflowStatus.FAILED
    assert "cannot prove" in resumed.steps[0].error
    assert "non-idempotent replay is unsafe" in resumed.steps[0].error
    assert len(failures) == 1
    assert failures[0].payload["recovery"] is True
    assert requested == []

    await bus.stop()
