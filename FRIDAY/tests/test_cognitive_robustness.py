import pytest
from unittest.mock import AsyncMock

from core.workflows.planner import BoundedPlanner
from core.workflows.prompt_planner import PromptPlanner
from core.workflows.recovery import WorkflowRecovery
from core.workflows.state import WorkflowGoal, WorkflowStep, WorkflowStatus
from core.tools.capability import Capability, ToolRisk, VerifySpec
from core.orchestrator.workflow_trigger import refusal_message


def _make_mock_ollama(response_text: str, success: bool = True):
    client = AsyncMock()
    metrics = AsyncMock()
    metrics.success = success
    metrics.error = None
    client.generate.return_value = (response_text, metrics)
    return client


@pytest.mark.asyncio
async def test_planner_native_impossible_refusal():
    impossible_json = '{"impossible": true, "reason": "FRIDAY cannot launch physical rockets"}'
    client = _make_mock_ollama(impossible_json)
    planner = PromptPlanner(client)

    plan = await planner.create_plan_for_goal("Launch a physical rocket to Mars")

    assert plan == []
    assert planner.last_rejection_reason == "impossible"
    assert "cannot launch physical rockets" in (planner.last_rejection_detail or "")

    msg = refusal_message(planner.last_rejection_reason, planner.last_rejection_detail)
    assert "I cannot perform that task" in msg
    assert "cannot launch physical rockets" in msg


@pytest.mark.asyncio
async def test_planner_native_impossible_refusal_list_format():
    impossible_list_json = '[{"impossible": true, "reason": "No access to internal email"}]'
    client = _make_mock_ollama(impossible_list_json)
    planner = PromptPlanner(client)

    plan = await planner.create_plan_for_goal("Read user internal inbox")

    assert plan == []
    assert planner.last_rejection_reason == "impossible"
    assert "No access to internal email" in (planner.last_rejection_detail or "")


def test_recovery_verification_failure_retry_safe_distinction():
    caps = {
        "verified_search": Capability(
            name="verified_search",
            description="Search with verify",
            risk=ToolRisk.SAFE,
            verify=VerifySpec(type="text_matches"),
            retry_safe=True,
        ),
        "verified_write": Capability(
            name="verified_write",
            description="Write with verify",
            risk=ToolRisk.RESTRICTED,
            verify=VerifySpec(type="file_exists"),
            retry_safe=False,
        ),
    }

    recovery = WorkflowRecovery(max_retries=2, capabilities=caps)

    # 1. Step with retry_safe: true fails verification -> evaluate_failure is True
    step_safe = WorkflowStep(id="s1", intent="verified_search", parameters={"query": "test"})
    step_safe.error = "verification failed: text did not match expected pattern"
    wf1 = WorkflowGoal(id="wf1", goal="Search", steps=[step_safe])
    assert recovery.evaluate_failure(wf1, step_safe) is True

    # 2. Step with retry_safe: false fails verification -> evaluate_failure is False
    step_unsafe = WorkflowStep(id="s2", intent="verified_write", parameters={"file_path": "out.txt"})
    step_unsafe.error = "verification failed: target file out.txt does not exist"
    wf2 = WorkflowGoal(id="wf2", goal="Write", steps=[step_unsafe])
    assert recovery.evaluate_failure(wf2, step_unsafe) is False


def test_semantic_verification_evaluates_goal_met_and_expected():
    from core.tools.verification import EffectVerifier
    from core.tools.tool_models import ToolResult

    verifier = EffectVerifier()
    cap_semantic = Capability(
        name="semantic_task",
        description="Task with semantic verification",
        risk=ToolRisk.SAFE,
        verify=VerifySpec(type="semantic", expect="build passing"),
    )

    # 1. Output satisfies expected string
    res_ok = ToolResult(True, "Workflow completed: build passing and all tests green.")
    v_ok = verifier.verify(cap_semantic, {}, res_ok)
    assert v_ok.checked is True
    assert v_ok.passed is True
    assert "satisfies semantic expectation" in v_ok.detail

    # 2. Output fails expected string
    res_bad = ToolResult(True, "Workflow completed: tests failed.")
    v_bad = verifier.verify(cap_semantic, {}, res_bad)
    assert v_bad.checked is True
    assert v_bad.passed is False
    assert "did not satisfy semantic expectation" in v_bad.detail

    # 3. Explicit goal_met flag in metadata overrides/satisfies
    res_goal_true = ToolResult(True, "Done", metadata={"goal_met": True})
    v_goal_true = verifier.verify(cap_semantic, {}, res_goal_true)
    assert v_goal_true.checked is True
    assert v_goal_true.passed is True

    res_goal_false = ToolResult(True, "Done", metadata={"goal_met": False})
    v_goal_false = verifier.verify(cap_semantic, {}, res_goal_false)
    assert v_goal_false.checked is True
    assert v_goal_false.passed is False


def test_durable_state_machine_new_lifecycle_states(tmp_path):
    from pathlib import Path
    from core.workflows.store import WorkflowStore

    store_path = Path(tmp_path) / "states.sqlite3"
    store = WorkflowStore(str(store_path))

    wf = WorkflowGoal(
        id="wf_states_01",
        goal="Test full lifecycle states",
        status=WorkflowStatus.PLANNING,
        steps=[
            WorkflowStep("s1", "build", {}, status=WorkflowStatus.VERIFYING),
            WorkflowStep("s2", "test", {}, status=WorkflowStatus.RETRYING),
            WorkflowStep("s3", "deploy", {}, status=WorkflowStatus.BLOCKED),
        ],
    )

    store.save_workflows({wf.id: wf})
    loaded = store.load_workflows()[wf.id]

    assert loaded.status == WorkflowStatus.PLANNING
    assert loaded.steps[0].status == WorkflowStatus.VERIFYING
    assert loaded.steps[1].status == WorkflowStatus.RETRYING
    assert loaded.steps[2].status == WorkflowStatus.BLOCKED

