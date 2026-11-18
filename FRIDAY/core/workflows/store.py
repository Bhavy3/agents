import json
import os
import sqlite3
import time
from .state import WorkflowGoal, WorkflowStep, WorkflowStatus


class WorkflowStore:
    """Handles persistence for workflow states."""

    def __init__(self, storage_path: str = "data/workflows/active_workflows.json"):
        self.storage_path = storage_path
        self._sqlite = storage_path.lower().endswith((".db", ".sqlite", ".sqlite3"))
        storage_dir = os.path.dirname(self.storage_path)
        if storage_dir:
            os.makedirs(storage_dir, exist_ok=True)
        if self._sqlite:
            with sqlite3.connect(self.storage_path) as connection:
                connection.execute("PRAGMA journal_mode=WAL")
                connection.execute("PRAGMA synchronous=NORMAL")
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS workflows ("
                    "workflow_id TEXT PRIMARY KEY, payload TEXT NOT NULL, updated_at REAL NOT NULL)"
                )
                connection.commit()

    def save_workflows(self, workflows: dict[str, WorkflowGoal]) -> None:
        data = {
            wid: self._goal_to_dict(goal) for wid, goal in workflows.items()
            if goal.status not in [WorkflowStatus.COMPLETED, WorkflowStatus.CANCELLED]
        }
        if self._sqlite:
            with sqlite3.connect(self.storage_path) as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute("DELETE FROM workflows")
                connection.executemany(
                    "INSERT INTO workflows(workflow_id, payload, updated_at) VALUES (?, ?, ?)",
                    [
                        (workflow_id, json.dumps(payload), time.time())
                        for workflow_id, payload in data.items()
                    ],
                )
                connection.commit()
            return
        with open(self.storage_path, "w") as f:
            json.dump(data, f, indent=2)

    def load_workflows(self) -> dict[str, WorkflowGoal]:
        if not os.path.exists(self.storage_path):
            return {}

        if self._sqlite:
            try:
                with sqlite3.connect(self.storage_path) as connection:
                    rows = connection.execute(
                        "SELECT workflow_id, payload FROM workflows"
                    ).fetchall()
                return {
                    workflow_id: self._dict_to_goal(workflow_id, json.loads(payload))
                    for workflow_id, payload in rows
                }
            except Exception:
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
                    "retry_count": s.retry_count,
                    "depends_on": s.depends_on,
                } for s in goal.steps
            ],
            "metadata": goal.metadata,
            "correlation_id": goal.correlation_id,
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
                retry_count=s.get("retry_count", 0),
                depends_on=s.get("depends_on", []),
            ) for s in data["steps"]
        ]
        return WorkflowGoal(
            id=workflow_id,
            goal=data["goal"],
            steps=steps,
            status=WorkflowStatus(data["status"]),
            created_at=data["created_at"],
            metadata=data.get("metadata", {}),
            correlation_id=data.get("correlation_id"),
        )
