import asyncio
import json
import unittest
from datetime import UTC, datetime, timedelta

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
    def test_event_bus_records_turn_milestones(self) -> None:
        async def scenario() -> dict[str, float | int]:
            metrics = RuntimeMetrics()
            bus = EventBus(metrics=metrics)
            correlation_id = "corr-bus"
            await bus.start()
            await bus.publish(
                Event.create(
                    EventType.CONVERSATION_TURN_STARTED,
                    {"turn_id": "turn-bus", "speaker": "user"},
                    "test",
                    correlation_id,
                )
            )
            await bus.publish(
                Event.create(
                    EventType.ASSISTANT_RESPONSE_PARTIAL,
                    {"turn_id": "turn-bus", "text": "hello"},
                    "test",
                    correlation_id,
                )
            )
            await bus.publish(
                Event.create(
                    EventType.TTS_PLAYBACK_STARTED,
                    {"chunk_id": "chunk-bus", "turn_id": "turn-bus"},
                    "test",
                    "tts-correlation",
                )
            )
            await bus.publish(
                Event.create(
                    EventType.ASSISTANT_RESPONSE_COMPLETED,
                    {"turn_id": "turn-bus", "text": "hello"},
                    "test",
                    correlation_id,
                )
            )
            await bus.drain()
            snapshot = metrics.snapshot()
            await bus.stop()
            return snapshot

        snapshot = asyncio.run(scenario())
        self.assertEqual(snapshot["turn_telemetry_count"], 1)
        self.assertGreaterEqual(snapshot["turn_first_response_p50_ms"], 0.0)
        self.assertGreaterEqual(snapshot["turn_tts_start_p50_ms"], 0.0)
        self.assertEqual(snapshot["turn_unaccounted_count"], 0)

    def test_turn_telemetry_is_correlated_bounded_and_aggregated(self) -> None:
        metrics = RuntimeMetrics(turn_telemetry_window_size=3)
        start = datetime(2026, 1, 1, tzinfo=UTC)
        metrics.record_turn_event(
            EventType.CONVERSATION_TURN_STARTED,
            "corr-1",
            start,
            {"turn_id": "turn-1"},
        )
        metrics.record_turn_event(EventType.INTENT_DETECTED, "corr-1", start + timedelta(milliseconds=10))
        metrics.record_turn_event(
            EventType.ASSISTANT_RESPONSE_PARTIAL,
            "corr-1",
            start + timedelta(milliseconds=20),
            {"turn_id": "turn-1"},
        )
        metrics.record_turn_event(
            EventType.ASSISTANT_RESPONSE_PARTIAL,
            "corr-1",
            start + timedelta(milliseconds=30),
            {"turn_id": "turn-1"},
        )
        metrics.record_turn_event(
            EventType.TTS_PLAYBACK_STARTED,
            "other-correlation",
            start + timedelta(milliseconds=40),
            {"turn_id": "turn-1"},
        )
        metrics.record_turn_event(
            EventType.ASSISTANT_RESPONSE_COMPLETED,
            "corr-1",
            start + timedelta(milliseconds=100),
            {"turn_id": "turn-1"},
        )
        metrics.record_turn_event(
            EventType.ASSISTANT_RESPONSE_COMPLETED,
            "corr-1",
            start + timedelta(milliseconds=110),
            {"turn_id": "turn-1"},
        )
        metrics.record_turn_event(
            EventType.CONVERSATION_TURN_ENDED,
            "corr-1",
            start + timedelta(milliseconds=120),
            {"turn_id": "turn-1"},
        )
        metrics.record_turn_event(EventType.ASSISTANT_RESPONSE_CANCELLED, "missing", start)

        snapshot = metrics.snapshot()
        self.assertEqual(snapshot["turn_telemetry_count"], 1)
        self.assertEqual(snapshot["turn_telemetry_p50_ms"], 100.0)
        self.assertEqual(snapshot["turn_telemetry_p95_ms"], 100.0)
        self.assertEqual(snapshot["turn_intent_p50_ms"], 10.0)
        self.assertEqual(snapshot["turn_first_response_p50_ms"], 20.0)
        self.assertEqual(snapshot["turn_tts_start_p50_ms"], 40.0)
        self.assertEqual(snapshot["turn_duplicate_completion_count"], 1)
        self.assertEqual(snapshot["turn_unaccounted_count"], 1)

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
        json.dumps(snapshot)
