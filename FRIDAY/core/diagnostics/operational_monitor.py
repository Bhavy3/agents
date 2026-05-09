from __future__ import annotations

import asyncio
from collections import deque
from datetime import UTC, datetime

from core.config.constants import (
    DEFAULT_MEMORY_GROWTH_WARNING_BYTES,
    DEFAULT_SNAPSHOT_INTERVAL_SECONDS,
    DEFAULT_TASK_GROWTH_WARNING_COUNT,
)
from core.diagnostics.memory_monitor import MemoryMonitor
from core.diagnostics.replay import FailureReplayRecorder
from core.diagnostics.snapshot import RuntimeSnapshot
from core.diagnostics.task_auditor import TaskAuditor
from core.events.bus import EventBus
from core.events.event_types import EventType
from core.events.models import Event, EventPriority
from core.metrics.metrics import RuntimeMetrics
from core.workers.base_worker import BaseWorker


class OperationalMonitorWorker(BaseWorker):
    def __init__(
        self,
        event_bus: EventBus,
        metrics: RuntimeMetrics,
        supervisor,
        replay_recorder: FailureReplayRecorder,
        interval_seconds: float = DEFAULT_SNAPSHOT_INTERVAL_SECONDS,
        memory_growth_warning_bytes: int = DEFAULT_MEMORY_GROWTH_WARNING_BYTES,
        task_growth_warning_count: int = DEFAULT_TASK_GROWTH_WARNING_COUNT,
    ) -> None:
        super().__init__("operational_monitor", event_bus)
        self.metrics = metrics
        self.supervisor = supervisor
        self.replay_recorder = replay_recorder
        self.interval_seconds = interval_seconds
        self.memory_monitor = MemoryMonitor(memory_growth_warning_bytes)
        self.task_auditor = TaskAuditor(task_growth_warning_count)
        self.snapshots: deque[RuntimeSnapshot] = deque(maxlen=500)
        self.anomalies: list[str] = []
        self._last_processed_events = 0
        self._last_queue_depth = 0
        self._stalled_queue_cycles = 0
        self._last_snapshot_at = datetime.now(UTC)

    async def work(self) -> None:
        import json
        from core.config.settings import load_settings
        settings = load_settings()
        snapshot_file = settings.log_dir / "metrics_snapshot.json"
        
        while not self.should_stop:
            self.heartbeat("operational_monitoring")
            snapshot = await self.capture_snapshot()
            self.snapshots.append(snapshot)
            await self.event_bus.publish(
                Event.create(
                    EventType.RUNTIME_SNAPSHOT,
                    snapshot.as_dict(),
                    self.name,
                    priority=EventPriority.LOW,
                )
            )
            try:
                snapshot_file.parent.mkdir(parents=True, exist_ok=True)
                snapshot_file.write_text(json.dumps(snapshot.as_dict(), indent=2))
            except Exception as e:
                pass
            await asyncio.sleep(self.interval_seconds)

    async def capture_snapshot(self) -> RuntimeSnapshot:
        memory_sample = self.memory_monitor.sample(self.event_bus.queue_depth)
        task_audit = self.task_auditor.audit()
        anomalies: list[str] = []

        memory_warning = self.memory_monitor.warning_reason(memory_sample)
        if memory_warning is not None:
            anomalies.append(memory_warning)
            await self._warn(EventType.MEMORY_WARNING, memory_warning)

        task_warning = self.task_auditor.warning_reason(task_audit)
        if task_warning is not None:
            anomalies.append(task_warning)
            await self._warn(EventType.TASK_AUDIT_WARNING, task_warning)

        previous_processed_events = self._last_processed_events
        previous_queue_depth = self._last_queue_depth
        deadlock_warning = self._detect_deadlock(previous_queue_depth, previous_processed_events)
        if deadlock_warning is not None:
            anomalies.append(deadlock_warning)
            await self._warn(EventType.DEADLOCK_WARNING, deadlock_warning)

        self.anomalies.extend(anomalies)
        now = datetime.now(UTC)
        elapsed = max((now - self._last_snapshot_at).total_seconds(), 0.001)
        processed_delta = self.metrics.processed_events - previous_processed_events
        self._last_processed_events = self.metrics.processed_events
        self._last_queue_depth = self.event_bus.queue_depth
        self._last_snapshot_at = now
        return RuntimeSnapshot(
            active_workers=self.supervisor.health_snapshot(),
            queue_state={
                "depth": self.event_bus.queue_depth,
                "max_size": self.event_bus.max_queue_size,
                "utilization_percent": round(self.event_bus.queue_utilization * 100, 3),
            },
            metrics=self.metrics.snapshot(),
            task_counts={
                "total": task_audit.total_tasks,
                "pending": task_audit.pending_tasks,
                "done": task_audit.done_tasks,
            },
            memory_usage=self.memory_monitor.trend(),
            event_rates={"processed_per_second": round(processed_delta / elapsed, 3)},
            anomalies=anomalies,
        )

    def _detect_deadlock(self, previous_queue_depth: int, previous_processed_events: int) -> str | None:
        queue_depth = self.event_bus.queue_depth
        processed_events = self.metrics.processed_events
        stalled = (
            queue_depth > 0
            and queue_depth >= previous_queue_depth
            and processed_events == previous_processed_events
        )
        if stalled:
            self._stalled_queue_cycles += 1
        else:
            self._stalled_queue_cycles = 0
        if self._stalled_queue_cycles >= 2:
            return "queue appears stalled with no event processing progress"
        return None

    async def _warn(self, event_type: EventType, reason: str) -> None:
        await self.event_bus.publish(
            Event.create(
                event_type,
                {"reason": reason},
                self.name,
                priority=EventPriority.CRITICAL,
            )
        )

    def latest_report_data(self) -> dict[str, object]:
        return {
            "snapshots": [snapshot.as_dict() for snapshot in self.snapshots],
            "anomalies": list(self.anomalies),
            "failure_replay": self.replay_recorder.recent(),
        }
