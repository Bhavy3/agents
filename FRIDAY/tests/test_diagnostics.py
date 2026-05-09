import asyncio
import unittest

from core.diagnostics.memory_monitor import MemoryMonitor
from core.diagnostics.operational_monitor import OperationalMonitorWorker
from core.diagnostics.replay import FailureReplayRecorder
from core.diagnostics.task_auditor import TaskAuditor
from core.events.bus import EventBus
from core.events.event_types import EventType
from core.events.models import Event, EventPriority
from core.metrics.metrics import RuntimeMetrics
from core.workers.supervisor import WorkerSupervisor


class DiagnosticsTests(unittest.TestCase):
    def test_failure_replay_records_critical_events(self) -> None:
        async def scenario() -> int:
            recorder = FailureReplayRecorder(max_events=5)
            await recorder.record(Event.create(EventType.USER_TEXT_RECEIVED, {"text": "ignored"}))
            await recorder.record(Event.create(EventType.WORKER_FAILED, {"worker": "x"}))
            return len(recorder.recent())

        self.assertEqual(asyncio.run(scenario()), 1)

    def test_memory_monitor_reports_trend(self) -> None:
        monitor = MemoryMonitor(growth_warning_bytes=1_000_000_000)
        monitor.sample(queue_depth=0)
        trend = monitor.trend()
        self.assertIn("current_bytes", trend)

    def test_task_auditor_counts_tasks(self) -> None:
        async def scenario() -> int:
            auditor = TaskAuditor(task_growth_warning_count=1000)
            return auditor.audit().total_tasks

        self.assertGreaterEqual(asyncio.run(scenario()), 1)

    def test_operational_monitor_creates_snapshot(self) -> None:
        async def scenario() -> dict[str, object]:
            metrics = RuntimeMetrics()
            bus = EventBus(metrics=metrics)
            supervisor = WorkerSupervisor(bus, [], metrics=metrics)
            recorder = FailureReplayRecorder()
            monitor = OperationalMonitorWorker(
                bus,
                metrics,
                supervisor,
                recorder,
                interval_seconds=1.0,
            )
            await bus.start()
            snapshot = await monitor.capture_snapshot()
            await bus.stop()
            return snapshot.as_dict()

        snapshot = asyncio.run(scenario())
        self.assertIn("metrics", snapshot)
        self.assertIn("memory_usage", snapshot)
