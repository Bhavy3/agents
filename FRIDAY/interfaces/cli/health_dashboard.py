from __future__ import annotations

from core.events.bus import EventBus
from core.metrics.metrics import RuntimeMetrics
from core.workers.supervisor import WorkerSupervisor


class TerminalHealthDashboard:
    def __init__(
        self,
        event_bus: EventBus,
        metrics: RuntimeMetrics,
        supervisor: WorkerSupervisor,
    ) -> None:
        self.event_bus = event_bus
        self.metrics = metrics
        self.supervisor = supervisor

    def render(self) -> str:
        metrics = self.metrics.snapshot()
        workers = self.supervisor.health_snapshot()
        lines = [
            "FRIDAY STATUS",
            f"uptime_seconds={metrics['uptime_seconds']}",
            f"queue_depth={self.event_bus.queue_depth}",
            f"processed_events={metrics['processed_events']}",
            f"failed_events={metrics['failed_events']}",
            f"dropped_events={metrics['dropped_events']}",
            f"restart_count={metrics['restart_count']}",
            f"avg_processing_seconds={metrics['average_processing_time_seconds']}",
            f"streams={self.metrics.stream_count} chunks={self.metrics.chunk_count} stream_errors={self.metrics.stream_error_count}",
            "workers:",
        ]
        for worker in workers:
            lines.append(
                " - "
                f"{worker['name']} state={worker['state']} "
                f"alive={worker['alive']} restarts={worker['restart_count']} "
                f"uptime={worker['uptime_seconds']}s task={worker['current_task']}"
            )
        return "\n".join(lines)

    def render_metrics(self) -> str:
        metrics = self.metrics.snapshot()
        lines = [
            "FRIDAY METRICS",
            f"uptime_seconds={metrics['uptime_seconds']}",
            f"processed_events={metrics['processed_events']}",
            f"failed_events={metrics['failed_events']}",
            f"dropped_events={metrics['dropped_events']}",
            f"restart_count={metrics['restart_count']}",
            f"avg_processing_seconds={metrics['average_processing_time_seconds']}",
        ]
        return "\n".join(lines)

    def render_workers(self) -> str:
        workers = self.supervisor.health_snapshot()
        lines = ["FRIDAY WORKERS"]
        for worker in workers:
            lines.append(
                " - "
                f"{worker['name']} state={worker['state']} "
                f"alive={worker['alive']} restarts={worker['restart_count']} "
                f"uptime={worker['uptime_seconds']}s task={worker['current_task']}"
            )
        return "\n".join(lines)
