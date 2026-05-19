import asyncio
import time
import uuid
from typing import Optional
from .state import WorkflowGoal, WorkflowStep, WorkflowStatus
from ..events.bus import EventBus
from ..events.event_types import EventType
from ..events.models import Event


class WorkflowEngine:
    """Manages the lifecycle and execution of multi-step autonomous workflows."""

    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus
        self.active_workflows: dict[str, WorkflowGoal] = {}
        self.max_steps = 5

    async def create_workflow(self, goal_text: str, steps: list[dict]) -> str:
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
            created_at=time.time()
        )
        
        self.active_workflows[workflow_id] = workflow
        return workflow_id

    async def start_workflow(self, workflow_id: str) -> None:
        if workflow_id not in self.active_workflows:
            return
        
        workflow = self.active_workflows[workflow_id]
        workflow.status = WorkflowStatus.RUNNING
        await self._execute_next_step(workflow)

    async def _execute_next_step(self, workflow: WorkflowGoal) -> None:
        # Find next pending step
        next_step = next((s for s in workflow.steps if s.status == WorkflowStatus.PENDING), None)
        
        if not next_step:
            workflow.status = WorkflowStatus.COMPLETED
            await self.event_bus.publish(Event.create(
                EventType.ACTION_GRAPH_COMPLETED,
                {"graph_id": workflow.id, "success": True},
                "workflow_engine"
            ))
            return

        next_step.status = WorkflowStatus.RUNNING
        
        # Resolve variables from previous step results
        # Example: {{step_0_result}} or {{step_0_output}}
        resolved_params = next_step.parameters.copy()
        
        def resolve_value(val: any) -> any:
            if isinstance(val, str) and "{{" in val:
                for i, s in enumerate(workflow.steps):
                    if s.result is not None:
                        val = val.replace(f"{{{{step_{i}_result}}}}", str(s.result))
                        val = val.replace(f"{{{{step_{i}_output}}}}", str(s.result))
            return val

        for key, value in resolved_params.items():
            resolved_params[key] = resolve_value(value)

        # Publish action request for the step
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
        workflow_id = step_id.split("_")[0]
        if workflow_id not in self.active_workflows:
            return

        workflow = self.active_workflows[workflow_id]
        step = next((s for s in workflow.steps if s.id == step_id), None)
        
        if not step:
            return

        if success:
            step.status = WorkflowStatus.COMPLETED
            step.result = output
            await self._execute_next_step(workflow)
        else:
            step.status = WorkflowStatus.FAILED
            step.error = error or "Unknown error"
            workflow.status = WorkflowStatus.FAILED
            await self.event_bus.publish(Event.create(
                EventType.ACTION_GRAPH_FAILED,
                {"graph_id": workflow.id, "error": step.error},
                "workflow_engine"
            ))
