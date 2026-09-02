from __future__ import annotations

import asyncio
import tracemalloc
from dataclasses import dataclass
from typing import Any

from core.events.event_types import EventType
from core.events.models import Event
from core.logging.logger import get_logger
from core.workers.base_worker import BaseWorker


class ValidationCrashWorker(BaseWorker):
    def __init__(self, event_bus: Any, crash_after_cycles: int = 3) -> None:
        super().__init__("validation_crash_worker", event_bus)
        self.crash_after_cycles = crash_after_cycles
        self.cycles = 0

    async def work(self) -> None:
        while not self.should_stop:
            self.cycles += 1
            self.heartbeat("validation_crash_simulation")
            if self.cycles % self.crash_after_cycles == 0:
                raise RuntimeError("simulated validation worker crash")
            await asyncio.sleep(0.2)


@dataclass(slots=True)
class RuntimeValidationReport:
    duration_seconds: float
    memory_current_bytes: int
    memory_peak_bytes: int
    metrics: dict[str, float | int]
    worker_health: list[dict[str, object]]
    restart_stats: dict[str, int]
    memory_trends: dict[str, int]
    event_throughput: dict[str, float]
    detected_anomalies: list[str]
    failure_replay: list[dict[str, object]]


class RuntimeValidator:
    def __init__(self, app) -> None:
        self.app = app
        self.logger = get_logger("validation.runtime")

    async def run(self, duration_seconds: float) -> RuntimeValidationReport:
        tracemalloc.start()
        await self.app.start()
        tasks = [
            asyncio.create_task(self._simulate_commands(duration_seconds), name="validation-commands"),
            asyncio.create_task(self._simulate_malformed_events(duration_seconds), name="validation-malformed"),
            asyncio.create_task(self._simulate_queue_pressure(duration_seconds), name="validation-queue-pressure"),
            asyncio.create_task(self._log_health(duration_seconds), name="validation-health-log"),
        ]
        try:
            await asyncio.sleep(duration_seconds)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await self.app.event_bus.drain()
            current, peak = tracemalloc.get_traced_memory()
            diagnostics = self.app.operational_monitor.latest_report_data()
            metrics = self.app.metrics.snapshot()
            report = RuntimeValidationReport(
                duration_seconds=duration_seconds,
                memory_current_bytes=current,
                memory_peak_bytes=peak,
                metrics=metrics,
                worker_health=self.app.supervisor.health_snapshot(),
                restart_stats={
                    str(worker["name"]): int(worker["restart_count"])
                    for worker in self.app.supervisor.health_snapshot()
                },
                memory_trends=self.app.operational_monitor.memory_monitor.trend(),
                event_throughput={
                    "processed_per_second": round(
                        self.app.metrics.processed_events / max(duration_seconds, 0.001),
                        3,
                    ),
                    "failed_per_second": round(
                        self.app.metrics.failed_events / max(duration_seconds, 0.001),
                        3,
                    ),
                    "dropped_per_second": round(
                        self.app.metrics.dropped_events / max(duration_seconds, 0.001),
                        3,
                    ),
                },
                detected_anomalies=list(diagnostics["anomalies"]),
                failure_replay=list(diagnostics["failure_replay"]),
            )
            self.logger.info(
                "runtime_validation_complete",
                extra={
                    "duration_seconds": duration_seconds,
                    "memory_current_bytes": current,
                    "memory_peak_bytes": peak,
                    "metrics": report.metrics,
                    "restart_stats": report.restart_stats,
                    "event_throughput": report.event_throughput,
                    "detected_anomalies": report.detected_anomalies,
                },
            )
            await self.app.stop()
            tracemalloc.stop()
        return report

    async def _simulate_commands(self, duration_seconds: float) -> None:
        commands = [
            "open chrome",
            "open folder C:\\tmp",
            "search google for event driven architecture",
            "help",
            "unknown fuzzy request",
            "delete files",
        ]
        end_time = asyncio.get_running_loop().time() + duration_seconds
        index = 0
        while asyncio.get_running_loop().time() < end_time:
            await self.app.event_bus.publish(
                Event.create(
                    EventType.USER_TEXT_RECEIVED,
                    {"text": commands[index % len(commands)]},
                    "runtime_validator",
                )
            )
            index += 1
            await asyncio.sleep(0.05)

    async def _simulate_malformed_events(self, duration_seconds: float) -> None:
        end_time = asyncio.get_running_loop().time() + duration_seconds
        while asyncio.get_running_loop().time() < end_time:
            await self.app.event_bus.publish_raw_for_validation("malformed-event")
            await asyncio.sleep(2.5)

    async def _simulate_queue_pressure(self, duration_seconds: float) -> None:
        end_time = asyncio.get_running_loop().time() + duration_seconds
        while asyncio.get_running_loop().time() < end_time:
            for _ in range(50):
                await self.app.event_bus.publish_nowait_safe(
                    Event.create(
                        EventType.USER_TEXT_RECEIVED,
                        {"text": "help"},
                        "runtime_validator_queue_pressure",
                    )
                )
            await asyncio.sleep(0.5)

    async def _log_health(self, duration_seconds: float) -> None:
        end_time = asyncio.get_running_loop().time() + duration_seconds
        while asyncio.get_running_loop().time() < end_time:
            self.logger.info(
                "runtime_validation_health",
                extra={
                    "metrics": self.app.metrics.snapshot(),
                    "workers": self.app.supervisor.health_snapshot(),
                },
            )
            await asyncio.sleep(5.0)
