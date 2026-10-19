import asyncio
import time
import uuid
import logging
from typing import Optional
from .state import WorkflowGoal, WorkflowStep, WorkflowStatus
from ..events.bus import EventBus
from ..events.event_types import EventType
from ..events.models import Event

logger = logging.getLogger(__name__)

# Cumulative character boundary for all chained output inserted into one step.
# Qwen2.5-3B tokenizer measurements: 1400 chars encoded to 401 URL-heavy,
# 373 JSON-heavy, and 496 mixed URL/JSON tokens. Keep the margin below 500.
MAX_STEP_OUTPUT_CHARS = 1400


class WorkflowEngine:
    """Manages the lifecycle and execution of multi-step autonomous workflows."""

    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus
        self.active_workflows: dict[str, WorkflowGoal] = {}
        self.max_steps = 5
        # A workflow step has one stable correlation id.  Keep the ids that
        # have already had a request published during this process so a
        # repeated start/recovery call cannot enqueue the same request twice.
        self._requested_action_step_ids: set[str] = set()

    async def create_workflow(
        self,
        goal_text: str,
        steps: list[dict],
        correlation_id: str | None = None,
    ) -> str:
        """Initializes a new workflow from a list of step definitions."""
        if len(steps) > self.max_steps:
            raise ValueError(f"Workflow exceeds max steps limit ({self.max_steps})")

        workflow_id = str(uuid.uuid4())[:8]
        workflow_steps = [
            WorkflowStep(
                id=f"{workflow_id}_{i}",
                intent=s["intent"],
                parameters=s.get("parameters", {})
            ) for i, s in enumerate(steps)
        ]

        workflow = WorkflowGoal(
            id=workflow_id,
            goal=goal_text,
            steps=workflow_steps,
            created_at=time.time(),
            correlation_id=correlation_id,
        )
        
        self.active_workflows[workflow_id] = workflow
        return workflow_id

    async def start_workflow(self, workflow_id: str) -> None:
        if workflow_id not in self.active_workflows:
            return
        
        workflow = self.active_workflows[workflow_id]
        if workflow.status in (
            WorkflowStatus.COMPLETED,
            WorkflowStatus.FAILED,
            WorkflowStatus.CANCELLED,
            WorkflowStatus.WAITING_CONFIRMATION,
        ):
            return
        if any(s.status == WorkflowStatus.WAITING_CONFIRMATION for s in workflow.steps):
            workflow.status = WorkflowStatus.WAITING_CONFIRMATION
            return
        workflow.status = WorkflowStatus.RUNNING
        await self._execute_next_step(workflow)

    async def fail_workflow_for_recovery(
        self,
        workflow: WorkflowGoal,
        reason: str,
        step: WorkflowStep | None = None,
    ) -> None:
        """Fail a workflow when restart recovery cannot safely continue it."""
        if step is not None:
            step.status = WorkflowStatus.FAILED
            step.error = reason
        workflow.status = WorkflowStatus.FAILED
        logger.error(
            "workflow_recovery_failed",
            extra={
                "workflow_id": workflow.id,
                "step_id": step.id if step else None,
                "reason": reason,
            },
        )
        await self.event_bus.publish(Event.create(
            EventType.ACTION_GRAPH_FAILED,
            {
                "graph_id": workflow.id,
                "error": reason,
                "failed_step": step.intent if step else None,
                "recovery": True,
            },
            "workflow_engine",
            correlation_id=workflow.correlation_id or workflow.id,
        ))
        await self.event_bus.publish(Event.create(
            EventType.RESPONSE_READY,
            {"text": f"Workflow recovery failed: {reason}"},
            "workflow_engine",
            correlation_id=workflow.correlation_id or workflow.id,
        ))

    async def cancel_workflow(self, workflow_id: str, reason: str = "User interrupted") -> None:
        """Cancels an active workflow at step boundary."""
        if workflow_id not in self.active_workflows:
            return
        workflow = self.active_workflows[workflow_id]
        if workflow.status in (WorkflowStatus.COMPLETED, WorkflowStatus.FAILED, WorkflowStatus.CANCELLED):
            return

        workflow.status = WorkflowStatus.CANCELLED
        # Mark pending steps as cancelled
        for step in workflow.steps:
            if step.status in (WorkflowStatus.PENDING, WorkflowStatus.WAITING_CONFIRMATION):
                step.status = WorkflowStatus.CANCELLED

        logger.info("workflow_cancelled", extra={"workflow_id": workflow_id, "reason": reason})
        await self.event_bus.publish(Event.create(
            EventType.ACTION_GRAPH_FAILED,
            {"graph_id": workflow.id, "error": reason, "cancelled": True},
            "workflow_engine",
            correlation_id=workflow.correlation_id or workflow.id,
        ))

    def _format_grounded_summary(self, workflow: WorkflowGoal) -> str:
        """Extracts the grounded answer from workflow step results.
        Result comes from the last NON-remember step's output.
        If a remember step ran, appends 'Saved to memory.'
        Never speaks raw read_text_file content.
        Truncates at sentence or word boundary, never mid-word.
        """
        if not workflow.steps:
            return f"Workflow '{workflow.goal}' completed successfully."

        has_remember_step = any(s.intent == "remember" and s.status == WorkflowStatus.COMPLETED for s in workflow.steps)

        # Find last non-remember step
        last_non_remember = None
        for s in reversed(workflow.steps):
            if s.intent != "remember":
                last_non_remember = s
                break

        summary_body = ""
        if last_non_remember:
            if last_non_remember.intent == "read_text_file":
                summary_body = "I've read the requested file."
            else:
                raw_out = (last_non_remember.result or "").strip()
                if raw_out and raw_out not in ("Saved", "No matches found"):
                    # Bound to 300 chars on sentence or word boundary
                    if len(raw_out) > 300:
                        truncated = raw_out[:300]
                        for punct in (". ", "! ", "? "):
                            idx = truncated.rfind(punct)
                            if idx > 150:
                                truncated = truncated[:idx + 1]
                                break
                        else:
                            idx = truncated.rfind(" ")
                            if idx > 150:
                                truncated = truncated[:idx]
                        summary_body = truncated.strip()
                    else:
                        summary_body = raw_out

        if not summary_body:
            summary_body = f"Workflow '{workflow.goal}' completed successfully."

        if has_remember_step:
            if summary_body.endswith("."):
                return f"{summary_body} Saved to memory."
            else:
                return f"{summary_body}. Saved to memory."

        return summary_body

    async def _execute_next_step(self, workflow: WorkflowGoal) -> None:
        if workflow.status in (
            WorkflowStatus.CANCELLED,
            WorkflowStatus.FAILED,
            WorkflowStatus.WAITING_CONFIRMATION,
        ):
            logger.info("workflow_step_skipped_cancelled", extra={"workflow_id": workflow.id})
            return

        # A running or waiting step is still active.  In particular, do not
        # interpret "no pending step" as completion while an action is in
        # flight, and do not publish a second request for it.
        active_step = next(
            (
                s for s in workflow.steps
                if s.status in (WorkflowStatus.RUNNING, WorkflowStatus.WAITING_CONFIRMATION)
            ),
            None,
        )
        if active_step is not None:
            if active_step.status == WorkflowStatus.WAITING_CONFIRMATION:
                workflow.status = WorkflowStatus.WAITING_CONFIRMATION
            return

        # Find next pending step
        next_step = next((s for s in workflow.steps if s.status == WorkflowStatus.PENDING), None)
        
        if not next_step:
            workflow.status = WorkflowStatus.COMPLETED
            summary_text = self._format_grounded_summary(workflow)
            await self.event_bus.publish(Event.create(
                EventType.ACTION_GRAPH_COMPLETED,
                {"graph_id": workflow.id, "success": True},
                "workflow_engine",
                correlation_id=workflow.correlation_id or workflow.id,
            ))
            await self.event_bus.publish(Event.create(
                EventType.RESPONSE_READY,
                {"text": summary_text},
                "workflow_engine",
                correlation_id=workflow.correlation_id or workflow.id,
            ))
            return

        if next_step.id in self._requested_action_step_ids:
            return

        next_step.status = WorkflowStatus.RUNNING
        workflow.status = WorkflowStatus.RUNNING
        step_idx = next(i for i, s in enumerate(workflow.steps) if s.id == next_step.id)
        total_steps = len(workflow.steps)

        # Progress tracking: emit step progress notice
        progress_msg = f"Step {step_idx + 1}/{total_steps}: Running {next_step.intent}..."
        await self.event_bus.publish(Event.create(
            EventType.ASSISTANT_RESPONSE_PARTIAL,
            {
                "text": progress_msg,
                "turn_id": workflow.id,
                "step_id": next_step.id,
                "workflow_id": workflow.id,
            },
            "workflow_engine",
            correlation_id=next_step.id,
        ))

        # Resolve variables with a strict CUMULATIVE prompt budget across ALL references in the step
        resolved_params = next_step.parameters.copy()
        remaining_budget = MAX_STEP_OUTPUT_CHARS

        for key, value in list(resolved_params.items()):
            if isinstance(value, str) and "{{" in value:
                for i, s in enumerate(workflow.steps):
                    placeholder_result = f"{{{{step_{i}_result}}}}"
                    placeholder_output = f"{{{{step_{i}_output}}}}"
                    if placeholder_result in value or placeholder_output in value:
                        raw_result = str(s.result or "")
                        # Allocate from the shared cumulative budget
                        inject_text = raw_result[:max(0, remaining_budget)]
                        remaining_budget = max(0, remaining_budget - len(inject_text))
                        value = value.replace(placeholder_result, inject_text)
                        value = value.replace(placeholder_output, inject_text)
                resolved_params[key] = value

        next_step.parameters = resolved_params

        # Publish action request for the step
        self._requested_action_step_ids.add(next_step.id)
        await self.event_bus.publish(Event.create(
            EventType.ACTION_REQUESTED,
            {
                "intent": next_step.intent,
                "parameters": resolved_params
            },
            "workflow_engine",
            correlation_id=next_step.id
        ))

    async def handle_action_result(self, step_id: str, success: bool, output: str, error: Optional[str] = None) -> None:
        # Extract workflow_id from step_id
        workflow_id = step_id.rsplit("_", 1)[0]
        if workflow_id not in self.active_workflows:
            return

        workflow = self.active_workflows[workflow_id]
        if workflow.status == WorkflowStatus.CANCELLED:
            # Late results are dropped
            logger.info("workflow_late_result_dropped", extra={"step_id": step_id, "workflow_id": workflow_id})
            return

        step = next((s for s in workflow.steps if s.id == step_id), None)
        if not step:
            return

        # Action results can be delivered more than once by a retried or
        # duplicated worker event. Only the currently running step may advance
        # the workflow; completed/failed steps are terminal for this result.
        if step.status not in (WorkflowStatus.RUNNING, WorkflowStatus.WAITING_CONFIRMATION):
            return

        if step.status == WorkflowStatus.WAITING_CONFIRMATION:
            # The confirmation system may transition directly from waiting to
            # execution without an ACTION_STARTED event in a test or a
            # lightweight integration.
            step.status = WorkflowStatus.RUNNING
            workflow.status = WorkflowStatus.RUNNING

        if success:
            step.status = WorkflowStatus.COMPLETED
            # Bound step output to prevent blowing up downstream prompts / context window
            step.result = (output or "")[:MAX_STEP_OUTPUT_CHARS]
            await self._execute_next_step(workflow)
        else:
            self._requested_action_step_ids.discard(step.id)
            step.status = WorkflowStatus.FAILED
            step.error = error or "Unknown error"
            workflow.status = WorkflowStatus.FAILED
            fail_msg = f"Workflow failed at step '{step.intent}': {step.error}"
            await self.event_bus.publish(Event.create(
                EventType.ACTION_GRAPH_FAILED,
                {"graph_id": workflow.id, "error": step.error, "failed_step": step.intent},
                "workflow_engine",
                correlation_id=workflow.correlation_id or workflow.id,
            ))
            await self.event_bus.publish(Event.create(
                EventType.RESPONSE_READY,
                {"text": fail_msg},
                "workflow_engine",
                correlation_id=workflow.correlation_id or workflow.id,
            ))
