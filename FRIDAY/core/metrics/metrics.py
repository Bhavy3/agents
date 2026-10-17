from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from statistics import quantiles

from core.events.event_types import EventType


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

    # Bounded, event-correlated turn telemetry.
    turn_telemetry_window_size: int = 100
    _active_turns: dict[str, dict[str, datetime | str]] = field(default_factory=dict, repr=False)
    _turn_id_to_correlation: dict[str, str] = field(default_factory=dict, repr=False)
    _completed_turns: deque[str] = field(default_factory=lambda: deque(maxlen=100), repr=False)
    _completed_turn_ids: deque[str] = field(default_factory=lambda: deque(maxlen=100), repr=False)
    _turn_elapsed_ms: deque[float] = field(default_factory=lambda: deque(maxlen=100), repr=False)
    _turn_milestone_elapsed_ms: dict[str, deque[float]] = field(
        default_factory=lambda: {
            "intent": deque(maxlen=100),
            "first_response": deque(maxlen=100),
            "tts_start": deque(maxlen=100),
        },
        repr=False,
    )
    turn_duplicate_completion_count: int = 0
    turn_cancelled_count: int = 0
    turn_unaccounted_count: int = 0

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

    def __post_init__(self) -> None:
        # Keep both completed correlation state and samples bounded even when
        # callers choose a smaller diagnostic window.
        size = max(1, self.turn_telemetry_window_size)
        self._completed_turns = deque(self._completed_turns, maxlen=size)
        self._completed_turn_ids = deque(self._completed_turn_ids, maxlen=size)
        self._turn_elapsed_ms = deque(self._turn_elapsed_ms, maxlen=size)
        self._turn_milestone_elapsed_ms = {
            name: deque(values, maxlen=size)
            for name, values in self._turn_milestone_elapsed_ms.items()
        }

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

    def record_turn_event(
        self,
        event_type: EventType,
        correlation_id: str,
        occurred_at: datetime | None = None,
        payload: dict[str, object] | None = None,
    ) -> None:
        """Record a turn milestone without retaining unbounded event history."""
        now = occurred_at or datetime.now(UTC)
        payload = payload or {}
        turn_id = payload.get("turn_id")
        turn_id = turn_id if isinstance(turn_id, str) else None
        if event_type is EventType.CONVERSATION_TURN_STARTED:
            if correlation_id not in self._active_turns and len(self._active_turns) >= self.turn_telemetry_window_size:
                _, evicted = self._active_turns.popitem()
                evicted_turn_id = evicted.get("turn_id")
                if isinstance(evicted_turn_id, str):
                    self._turn_id_to_correlation.pop(evicted_turn_id, None)
                self.turn_unaccounted_count += 1
            self._active_turns[correlation_id] = {"started": now}
            if turn_id is not None:
                self._active_turns[correlation_id]["turn_id"] = turn_id
                self._turn_id_to_correlation[turn_id] = correlation_id
            return

        key = correlation_id
        if key not in self._active_turns and turn_id is not None:
            key = self._turn_id_to_correlation.get(turn_id, key)
        turn = self._active_turns.get(key)
        if turn is None:
            if event_type is EventType.ASSISTANT_RESPONSE_COMPLETED and (
                correlation_id in self._completed_turns
                or (turn_id is not None and turn_id in self._completed_turn_ids)
            ):
                self.turn_duplicate_completion_count += 1
            elif event_type is EventType.CONVERSATION_TURN_ENDED and (
                correlation_id in self._completed_turns
                or (turn_id is not None and turn_id in self._completed_turn_ids)
            ):
                return
            elif event_type in {
                EventType.ASSISTANT_RESPONSE_COMPLETED,
                EventType.ASSISTANT_RESPONSE_CANCELLED,
                EventType.CONVERSATION_TURN_ENDED,
            }:
                self.turn_unaccounted_count += 1
            return
        started = turn["started"]
        if not isinstance(started, datetime):
            self.turn_unaccounted_count += 1
            return
        elapsed = max(0.0, (now - started).total_seconds() * 1000)
        if event_type is EventType.ASSISTANT_RESPONSE_PARTIAL and "first_response" in turn:
            return
        if event_type is EventType.TTS_PLAYBACK_STARTED and "tts" in turn:
            return
        milestone = {
            EventType.INTENT_DETECTED: "intent",
            EventType.ASSISTANT_RESPONSE_PARTIAL: "first_response",
            EventType.TTS_PLAYBACK_STARTED: "tts_start",
        }.get(event_type)
        if milestone:
            turn[milestone] = now
            self._turn_milestone_elapsed_ms[milestone].append(elapsed)
        elif event_type in {EventType.ASSISTANT_RESPONSE_COMPLETED,
                            EventType.ASSISTANT_RESPONSE_CANCELLED,
                            EventType.CONVERSATION_TURN_ENDED}:
            if event_type is EventType.CONVERSATION_TURN_ENDED and "terminal" in turn:
                return
            self._turn_elapsed_ms.append(elapsed)
            if event_type is EventType.ASSISTANT_RESPONSE_CANCELLED:
                self.turn_cancelled_count += 1
            if event_type in {EventType.ASSISTANT_RESPONSE_COMPLETED, EventType.ASSISTANT_RESPONSE_CANCELLED}:
                self._completed_turns.append(key)
                completed_turn_id = turn.get("turn_id")
                if isinstance(completed_turn_id, str):
                    self._completed_turn_ids.append(completed_turn_id)
            turn["terminal"] = now
            del self._active_turns[key]
            completed_turn_id = turn.get("turn_id")
            if isinstance(completed_turn_id, str):
                self._turn_id_to_correlation.pop(completed_turn_id, None)

    @staticmethod
    def _percentile(values: list[float], percentile: float) -> float:
        if not values:
            return 0.0
        if len(values) == 1:
            return values[0]
        return quantiles(values, n=100, method="inclusive")[int(percentile) - 1]

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
            "turn_telemetry_count": len(self._turn_elapsed_ms),
            "turn_telemetry_p50_ms": round(self._percentile(list(self._turn_elapsed_ms), 50), 3),
            "turn_telemetry_p95_ms": round(self._percentile(list(self._turn_elapsed_ms), 95), 3),
            "turn_intent_p50_ms": round(self._percentile(list(self._turn_milestone_elapsed_ms["intent"]), 50), 3),
            "turn_intent_p95_ms": round(self._percentile(list(self._turn_milestone_elapsed_ms["intent"]), 95), 3),
            "turn_first_response_p50_ms": round(self._percentile(list(self._turn_milestone_elapsed_ms["first_response"]), 50), 3),
            "turn_first_response_p95_ms": round(self._percentile(list(self._turn_milestone_elapsed_ms["first_response"]), 95), 3),
            "turn_tts_start_p50_ms": round(self._percentile(list(self._turn_milestone_elapsed_ms["tts_start"]), 50), 3),
            "turn_tts_start_p95_ms": round(self._percentile(list(self._turn_milestone_elapsed_ms["tts_start"]), 95), 3),
            "turn_duplicate_completion_count": self.turn_duplicate_completion_count,
            "turn_cancelled_count": self.turn_cancelled_count,
            "turn_unaccounted_count": self.turn_unaccounted_count,
        }
