from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass(slots=True)
class RuntimeMetrics:
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    processed_events: int = 0
    failed_events: int = 0
    dropped_events: int = 0
    restart_count: int = 0
    total_processing_time_seconds: float = 0.0
    queue_depth: int = 0
    active_workers: int = 0
    stream_count: int = 0
    chunk_count: int = 0
    stream_error_count: int = 0
    
    # TTS Playback Metrics
    stream_end_fires: int = 0
    safety_net_fires: int = 0
    tts_rolling_window: deque[str] = field(default_factory=lambda: deque(maxlen=20))
    
    # Memory Metrics
    memories_stored: int = 0
    recall_queries: int = 0
    denied_memory_writes: int = 0
    memory_db_latency_ms: float = 0.0
    degraded_memory_mode: bool = False

    # Vision Metrics
    screenshots_captured: int = 0
    ocr_requests: int = 0
    ocr_failures: int = 0
    visual_context_requests: int = 0
    vision_degraded_mode: bool = False
    average_ocr_latency_ms: float = 0.0

    # Tool Runtime Metrics
    tools_executed: int = 0
    tools_cancelled: int = 0
    tools_denied: int = 0
    action_graphs_executed: int = 0
    action_graph_failures: int = 0
    average_tool_latency_ms: float = 0.0
    subprocess_count: int = 0
    tool_runtime_degraded_mode: bool = False

    def record_processed_event(self, duration_seconds: float) -> None:
        self.processed_events += 1
        self.total_processing_time_seconds += duration_seconds

    def record_failed_event(self) -> None:
        self.failed_events += 1

    def record_dropped_event(self) -> None:
        self.dropped_events += 1

    def record_restart(self) -> None:
        self.restart_count += 1

    def record_tts_completion(self, trigger: str) -> None:
        if trigger == "stream_end":
            self.stream_end_fires += 1
            self.tts_rolling_window.append("stream_end")
        elif trigger == "safety_net":
            self.safety_net_fires += 1
            self.tts_rolling_window.append("safety_net")

    @property
    def tts_safety_net_ratio(self) -> float:
        total = self.stream_end_fires + self.safety_net_fires
        if total == 0:
            return 0.0
        return self.safety_net_fires / total

    @property
    def average_processing_time_seconds(self) -> float:
        if self.processed_events == 0:
            return 0.0
        return self.total_processing_time_seconds / self.processed_events

    @property
    def uptime_seconds(self) -> float:
        return (datetime.now(UTC) - self.started_at).total_seconds()

    def snapshot(self) -> dict[str, float | int]:
        return {
            "uptime_seconds": round(self.uptime_seconds, 3),
            "processed_events": self.processed_events,
            "failed_events": self.failed_events,
            "dropped_events": self.dropped_events,
            "restart_count": self.restart_count,
            "average_processing_time_seconds": round(self.average_processing_time_seconds, 6),
            "queue_depth": self.queue_depth,
            "active_workers": self.active_workers,
            "stream_end_fires": self.stream_end_fires,
            "safety_net_fires": self.safety_net_fires,
            "tts_safety_net_ratio": round(self.tts_safety_net_ratio, 4),
        }
