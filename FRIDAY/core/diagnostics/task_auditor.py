from __future__ import annotations

import asyncio
from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class TaskAudit:
    total_tasks: int
    pending_tasks: int
    done_tasks: int
    current_task_names: list[str]


class TaskAuditor:
    def __init__(self, task_growth_warning_count: int) -> None:
        self.task_growth_warning_count = task_growth_warning_count
        self._baseline_total: int | None = None

    def audit(self) -> TaskAudit:
        tasks = list(asyncio.all_tasks())
        total = len(tasks)
        if self._baseline_total is None:
            self._baseline_total = total
        return TaskAudit(
            total_tasks=total,
            pending_tasks=sum(1 for task in tasks if not task.done()),
            done_tasks=sum(1 for task in tasks if task.done()),
            current_task_names=[task.get_name() for task in tasks],
        )

    def warning_reason(self, audit: TaskAudit) -> str | None:
        if self._baseline_total is None:
            return None
        growth = audit.total_tasks - self._baseline_total
        if growth > self.task_growth_warning_count:
            return f"async task growth exceeded threshold: {growth} tasks"
        return None
