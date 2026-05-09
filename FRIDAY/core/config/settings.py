from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import os
from pathlib import Path

from core.config.constants import (
    DEFAULT_EVENT_HANDLER_TIMEOUT_SECONDS,
    DEFAULT_EVENT_MAX_AGE_SECONDS,
    DEFAULT_MAX_RESTARTS_PER_MINUTE,
    DEFAULT_MEMORY_GROWTH_WARNING_BYTES,
    DEFAULT_QUEUE_SIZE,
    DEFAULT_SNAPSHOT_INTERVAL_SECONDS,
    DEFAULT_TASK_GROWTH_WARNING_COUNT,
    DEFAULT_WORKER_HEARTBEAT_TIMEOUT_SECONDS,
    DEFAULT_COMMAND_TIMEOUT_SECONDS,
    DEFAULT_SHUTDOWN_TIMEOUT_SECONDS,
    DRY_RUN_MODE,
)


class RuntimeMode(StrEnum):
    DEVELOPMENT = "development"
    TESTING = "testing"
    PRODUCTION = "production"


@dataclass(slots=True, frozen=True)
class Settings:
    root_dir: Path
    queue_size: int = DEFAULT_QUEUE_SIZE
    dry_run: bool = DRY_RUN_MODE
    ollama_model: str = "qwen2.5:7b"
    ollama_base_url: str = "http://localhost:11434"
    ollama_timeout_seconds: float = 30.0
    ollama_max_retries: int = 2
    runtime_mode: RuntimeMode = RuntimeMode.DEVELOPMENT
    event_max_age_seconds: float = DEFAULT_EVENT_MAX_AGE_SECONDS
    event_handler_timeout_seconds: float = DEFAULT_EVENT_HANDLER_TIMEOUT_SECONDS
    worker_heartbeat_timeout_seconds: float = DEFAULT_WORKER_HEARTBEAT_TIMEOUT_SECONDS
    command_timeout_seconds: float = DEFAULT_COMMAND_TIMEOUT_SECONDS
    shutdown_timeout_seconds: float = DEFAULT_SHUTDOWN_TIMEOUT_SECONDS
    max_restarts_per_minute: int = DEFAULT_MAX_RESTARTS_PER_MINUTE
    memory_growth_warning_bytes: int = DEFAULT_MEMORY_GROWTH_WARNING_BYTES
    task_growth_warning_count: int = DEFAULT_TASK_GROWTH_WARNING_COUNT
    snapshot_interval_seconds: float = DEFAULT_SNAPSHOT_INTERVAL_SECONDS
    log_level: str = "INFO"
    json_logging: bool = True
    tts_model_path: str | None = None
    tts_config_path: str | None = None

    @property
    def data_dir(self) -> Path:
        return self.root_dir / "data"

    @property
    def log_dir(self) -> Path:
        return self.data_dir / "logs"


def load_settings() -> Settings:
    mode_value = os.getenv("FRIDAY_RUNTIME_MODE", RuntimeMode.DEVELOPMENT.value).lower()
    try:
        runtime_mode = RuntimeMode(mode_value)
    except ValueError:
        runtime_mode = RuntimeMode.DEVELOPMENT
    if runtime_mode == RuntimeMode.TESTING:
        return Settings(
            root_dir=Path(__file__).resolve().parents[2],
            runtime_mode=runtime_mode,
            queue_size=300,
            event_max_age_seconds=30.0,
            event_handler_timeout_seconds=2.0,
            worker_heartbeat_timeout_seconds=5.0,
            max_restarts_per_minute=20,
            memory_growth_warning_bytes=20_000_000,
            task_growth_warning_count=50,
            snapshot_interval_seconds=5.0,
        )
    if runtime_mode == RuntimeMode.PRODUCTION:
        return Settings(
            root_dir=Path(__file__).resolve().parents[2],
            runtime_mode=runtime_mode,
            queue_size=5000,
            event_max_age_seconds=60.0,
            event_handler_timeout_seconds=5.0,
            worker_heartbeat_timeout_seconds=90.0,
            max_restarts_per_minute=5,
            memory_growth_warning_bytes=100_000_000,
            task_growth_warning_count=200,
            snapshot_interval_seconds=30.0,
        )
    return Settings(root_dir=Path(__file__).resolve().parents[2], runtime_mode=runtime_mode)
