import json
import os
from .state import WorkflowGoal, WorkflowStep, WorkflowStatus


class WorkflowStore:
    """Handles persistence for workflow states."""

    def __init__(self, storage_path: str = "data/workflows/active_workflows.json"):
        self.storage_path = storage_path
        os.makedirs(os.path.dirname(self.storage_path), exist_ok=True)

    def save_workflows(self, workflows: dict[str, WorkflowGoal]) -> None:
        data = {
            wid: self._goal_to_dict(goal) for wid, goal in workflows.items()
            if goal.status not in [WorkflowStatus.COMPLETED, WorkflowStatus.CANCELLED]
        }
        with open(self.storage_path, "w") as f:
            json.dump(data, f, indent=2)

    def load_workflows(self) -> dict[str, WorkflowGoal]:
        if not os.path.exists(self.storage_path):
            return {}
        
        try:
            with open(self.storage_path, "r") as f:
                data = json.load(f)
                return {wid: self._dict_to_goal(wid, g_dict) for wid, g_dict in data.items()}
        except Exception:
            return {}

    def _goal_to_dict(self, goal: WorkflowGoal) -> dict:
        return {
            "goal": goal.goal,
            "status": goal.status.value,
            "created_at": goal.created_at,
            "steps": [
                {
                    "id": s.id,
                    "intent": s.intent,
                    "parameters": s.parameters,
                    "status": s.status.value,
                    "result": s.result,
                    "error": s.error,
                    "retry_count": s.retry_count
                } for s in goal.steps
            ]
        }

    def _dict_to_goal(self, workflow_id: str, data: dict) -> WorkflowGoal:
        steps = [
            WorkflowStep(
                id=s["id"],
                intent=s["intent"],
                parameters=s["parameters"],
                status=WorkflowStatus(s["status"]),
                result=s.get("result"),
                error=s.get("error"),
                retry_count=s.get("retry_count", 0)
            ) for s in data["steps"]
        ]
        return WorkflowGoal(
            id=workflow_id,
            goal=data["goal"],
            steps=steps,
            status=WorkflowStatus(data["status"]),
            created_at=data["created_at"]
        )
