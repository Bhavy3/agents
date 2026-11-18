from __future__ import annotations

import asyncio
import contextlib
import os
from collections.abc import Callable

from core.config.settings import Settings, load_settings
from core.diagnostics.operational_monitor import OperationalMonitorWorker
from core.diagnostics.replay import FailureReplayRecorder
from core.events.bus import EventBus
from core.events.event_types import EventType
from core.events.models import Event
from core.tools.tool_worker import ToolWorker
from core.logging.logger import configure_logging, get_logger, shutdown_logging
from core.llm.ollama_client import OllamaClient
from core.llm.model_manager import ModelManager
from core.llm.stream_aggregator import ResponseAggregator
from core.llm.streaming_worker import StreamingLlmWorker
from core.router.llm_fallback import LlmFallbackRouter
from core.memory.command_history import CommandHistory
from core.recovery.healthcheck import HealthcheckWorker
from core.recovery.recovery_manager import RecoveryManager
from core.router.intent_router import IntentRouter
from core.memory.memory_worker import MemoryWorker
from core.workers.terminal_observer import TerminalObserverWorker
from core.workers.mail_watcher import MailWatcherWorker
from core.vision.screen_capture import ScreenCaptureWorker
from core.vision.ocr_worker import OCRWorker
from core.vision.window_monitor import WindowMonitorWorker
from core.vision.visual_context import VisualContextManager
from core.validation.runtime_validator import RuntimeValidationReport, RuntimeValidator, ValidationCrashWorker
from core.personality.personality_worker import PersonalityWorker
from core.cognition.cognitive_state import CognitiveStateEngine
from core.cognition.cognitive_worker import CognitiveWorker
from core.workflows.workflow_worker import WorkflowWorker
from core.workflows.prompt_planner import PromptPlanner
from core.workers.supervisor import WorkerSupervisor
from interfaces.cli.health_dashboard import TerminalHealthDashboard
from interfaces.cli.terminal_ui import TerminalUI


def has_audio_output_endpoint() -> bool:
    """Return True when at least one audio device can actually play output.

    A headless or WASAPI-less session leaves Pipecat blocked on an unread
    output transport, which stalls shutdown until the safety net fires.
    """
    try:
        import sounddevice as sd

        devices = sd.query_devices()
    except Exception as exc:
        get_logger("app").warning(
            "audio_device_probe_failed",
            extra={"error": repr(exc)},
        )
        return False
    for device in devices:
        try:
            if int(device.get("max_output_channels") or 0) > 0:
                return True
        except (TypeError, ValueError):
            continue
    return False


class FridayApp:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or load_settings()
        configure_logging(
            self.settings.log_dir,
            level=self.settings.log_level,
            json_logging=self.settings.json_logging,
            console_level=self.settings.console_log_level,
        )
        self.logger = get_logger("app")
        from core.metrics.metrics import RuntimeMetrics

        self.metrics = RuntimeMetrics()
        self.replay_recorder = FailureReplayRecorder()
        self.event_bus = EventBus(
            max_queue_size=self.settings.queue_size,
            metrics=self.metrics,
            event_max_age_seconds=self.settings.event_max_age_seconds,
            handler_timeout_seconds=self.settings.event_handler_timeout_seconds,
        )
        self.command_history = CommandHistory()
        self.cognitive_state_engine = CognitiveStateEngine(self.event_bus)
        # Public compatibility alias for callers that use the shorter name.
        self.cognitive_state = self.cognitive_state_engine
        self.cognitive_worker = CognitiveWorker(
            self.event_bus,
            state_engine=self.cognitive_state_engine,
        )
        
        from core.llm.local_llm_client import create_llm_client
        self.ollama_client = create_llm_client(
            base_url=self.settings.ollama_base_url,
            model=self.settings.ollama_model,
            timeout_seconds=self.settings.ollama_timeout_seconds,
            max_retries=self.settings.ollama_max_retries,
            provider=self.settings.llm_provider,
        )
        self.model_manager = ModelManager(event_bus=self.event_bus, client=self.ollama_client)
        self.stream_aggregator = ResponseAggregator(self.event_bus, metrics=self.metrics)
        self.streaming_worker = StreamingLlmWorker(
            self.event_bus,
            self.ollama_client,
            self.stream_aggregator,
            model_manager=self.model_manager,
        )
        self.tool_worker = ToolWorker(self.event_bus, metrics=self.metrics, query_client=self.ollama_client)
        valid_tools = self.tool_worker.registry.list_tools()
        self.llm_fallback = LlmFallbackRouter(
            ollama_client=self.ollama_client,
            command_history=self.command_history,
            event_bus=self.event_bus,
            streaming_worker=self.streaming_worker,
            valid_tools=valid_tools,
            model_manager=self.model_manager,
        )
        self.intent_router = IntentRouter(self.event_bus, llm_fallback=self.llm_fallback)
        self.memory_worker = MemoryWorker(
            self.event_bus,
            metrics=self.metrics,
            db_path=os.getenv("FRIDAY_MEMORY_DB_PATH", "data/memory/friday_memory.db"),
        )
        self.screen_capture = ScreenCaptureWorker(self.event_bus, metrics=self.metrics)
        self.ocr_worker = OCRWorker(self.event_bus, metrics=self.metrics)
        self.window_monitor = WindowMonitorWorker(self.event_bus)
        self.visual_context = VisualContextManager(self.event_bus)
        self.visual_context.start()
        self.personality_worker = PersonalityWorker(self.event_bus)
        self.workflow_worker = WorkflowWorker(self.event_bus)
        # Validate plans against the same registry used by the live tool
        # worker, rather than a second default registry.
        # Optional strong planner: a larger model authors the plan, while the
        # turn itself keeps running on the fast primary model.
        planner_model = (os.getenv("FRIDAY_PLANNER_MODEL") or "").strip().lower()
        strong_planner_client = None
        if planner_model in ("7b", "strong", "large"):
            strong_planner_client = create_llm_client(
                base_url=os.getenv("FRIDAY_LLM_BASE_URL_7B", "http://127.0.0.1:8081"),
                model=os.getenv("FRIDAY_PLANNER_MODEL_NAME", "qwen2.5-7b-instruct-q4_k_m"),
                timeout_seconds=float(os.getenv("FRIDAY_PLANNER_TIMEOUT_SECONDS", "180")),
                max_retries=1,
                provider=self.settings.llm_provider,
            )
            # A CPU-only 7B plans at ~2 tok/s. Offload layers for the planner
            # sidecar only; the rest of the model manager is unchanged.
            self.model_manager.model_gpu_layers["7b"] = int(
                os.getenv("FRIDAY_PLANNER_GPU_LAYERS", "24")
            )
            self.logger.info(
                "planner_strong_client_configured",
                extra={"base_url": strong_planner_client.base_url, "model": strong_planner_client.model},
            )
        self.prompt_planner = PromptPlanner(
            self.ollama_client,
            tool_registry=self.tool_worker.registry,
            strong_ollama_client=strong_planner_client,
        )
        self.recovery_manager = RecoveryManager(self.event_bus)
        healthcheck_interval = max(1.0, min(30.0, self.settings.worker_heartbeat_timeout_seconds / 3))
        from core.audio.transport import AudioTransportWorker
        from core.audio.vad import VadWorker
        from core.audio.stt import SttWorker
        from core.audio.tts import TtsWorker
        from core.orchestrator.conversation import OrchestratorWorker
        from core.audio.pipecat_worker import PipecatAudioWorker
        
        self.orchestrator = OrchestratorWorker(
            self.event_bus,
            self.intent_router,
            self.streaming_worker,
            prompt_planner=self.prompt_planner,
            response_timeout_seconds=self.settings.ollama_timeout_seconds,
            enable_presence_ack=getattr(self.settings, 'enable_presence_ack', False),
            cognitive_state=self.cognitive_state_engine,
            model_manager=self.model_manager,
        )
        
        tts_worker = TtsWorker(
            self.event_bus,
            model_path=self.settings.tts_model_path,
            config_path=self.settings.tts_config_path,
        )
        
        runtime_workers = [
            HealthcheckWorker(self.event_bus, interval_seconds=healthcheck_interval),
            self.cognitive_worker,
            self.orchestrator,
            self.tool_worker,
            self.personality_worker,
            self.workflow_worker,
            self.memory_worker,
            self.screen_capture,
            self.ocr_worker,
            self.window_monitor,
            TerminalObserverWorker(self.event_bus),
        ]
        audio_enabled = getattr(self.settings, "audio_enabled", True)
        audio_disabled_reason = "FRIDAY_AUDIO_ENABLED=false"
        if audio_enabled and not has_audio_output_endpoint():
            audio_enabled = False
            audio_disabled_reason = "no_audio_output_endpoint_detected"
        if audio_enabled:
            runtime_workers[1:1] = [PipecatAudioWorker(self.event_bus), tts_worker]
        else:
            self.logger.info("audio_pipeline_disabled", extra={"reason": audio_disabled_reason})

        if getattr(self.settings, "mail_watcher_enabled", False):
            if self.settings.mail_user and self.settings.mail_password:
                runtime_workers.append(MailWatcherWorker(
                    self.event_bus,
                    host=self.settings.mail_imap_host,
                    user=self.settings.mail_user,
                    password=self.settings.mail_password,
                    poll_interval_seconds=self.settings.mail_poll_interval_seconds,
                ))
            else:
                self.logger.warning(
                    "mail_watcher_missing_credentials",
                    extra={"reason": "set FRIDAY_MAIL_USER and FRIDAY_MAIL_PASSWORD"},
                )
        else:
            self.logger.info("mail_watcher_disabled", extra={"reason": "FRIDAY_MAIL_ENABLED!=true"})

        self.supervisor = WorkerSupervisor(
            self.event_bus,
            workers=runtime_workers,
            metrics=self.metrics,
            heartbeat_timeout_seconds=self.settings.worker_heartbeat_timeout_seconds,
            max_restarts_per_minute=self.settings.max_restarts_per_minute,
            max_total_restarts=self.settings.max_total_restarts,
            max_total_restarts_window_seconds=self.settings.max_total_restarts_window_seconds,
        )

        self.operational_monitor = OperationalMonitorWorker(
            self.event_bus,
            self.metrics,
            self.supervisor,
            self.replay_recorder,
            interval_seconds=self.settings.snapshot_interval_seconds,
            memory_growth_warning_bytes=self.settings.memory_growth_warning_bytes,
            task_growth_warning_count=self.settings.task_growth_warning_count,
        )
        self.supervisor.workers.append(self.operational_monitor)
        self.dashboard = TerminalHealthDashboard(self.event_bus, self.metrics, self.supervisor)
        self.terminal_ui = TerminalUI(self.event_bus, self.dashboard)
        self._shutdown_event = asyncio.Event()
        self._started = False

    async def _ensure_planner_sidecar(self) -> None:
        """Start the strong planner server on demand instead of by hand.

        Only runs when FRIDAY_PLANNER_MODEL asked for a strong planner. A
        failure here is logged and planning falls back to the primary model;
        it must never block startup.
        """
        if self.prompt_planner.strong_planner is None:
            return
        if self.prompt_planner._endpoint_healthy():
            self.logger.info("planner_sidecar_already_running")
            return
        process, error = await self.model_manager._start_healthy_process("7b", port=8081)
        if process is None:
            self.logger.warning("planner_sidecar_start_failed", extra={"error": error})
            return
        self.model_manager.model_processes["7b"] = process
        self.prompt_planner._strong_health_checked_at = 0.0
        self.logger.info("planner_sidecar_started", extra={"port": 8081})

    async def run(self) -> None:
        await self.start()
        try:
            ui_task = asyncio.create_task(self.terminal_ui.start(), name="terminal-ui")
            shutdown_task = asyncio.create_task(self._shutdown_event.wait(), name="shutdown-waiter")
            done, pending = await asyncio.wait(
                {ui_task, shutdown_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            for task in done:
                with contextlib.suppress(asyncio.CancelledError):
                    task.result()
        finally:
            await self.stop()

    async def run_validation(self, duration_seconds: float) -> RuntimeValidationReport:
        if not self._started:
            self.supervisor.workers.append(ValidationCrashWorker(self.event_bus))
        validator = RuntimeValidator(self)
        return await validator.run(duration_seconds)

    async def start(self) -> None:
        if self._started:
            return
        await self.event_bus.start()
        self.event_bus.subscribe_all(self.replay_recorder.record)
        
        # Phase 2.0: Health check for Ollama
        ollama_available = await self.ollama_client.health_check()
        if not ollama_available:
            self.logger.warning("ollama_unavailable_at_startup", extra={"model": self.ollama_client.model})
        await self._ensure_planner_sidecar()
        
        self.event_bus.subscribe(EventType.SYSTEM_SHUTDOWN_REQUESTED, self._handle_shutdown)
        await self.intent_router.start()
        await self.recovery_manager.start()
        await self.supervisor.start()
        await self.event_bus.publish(Event.create(EventType.SYSTEM_READY, {}, "app"))
        self._started = True
        self.logger.info(
            "friday_started",
            extra={"dry_run": self.settings.dry_run, "runtime_mode": self.settings.runtime_mode.value},
        )

    async def stop(self) -> None:
        if not self._started:
            shutdown_logging()
            return
        self._started = False
        self.logger.info("friday_stopping", extra={"timeout": self.settings.shutdown_timeout_seconds})
        
        try:
            await asyncio.wait_for(self._perform_shutdown(), timeout=self.settings.shutdown_timeout_seconds)
            self.logger.info("friday_stopped")
        except (asyncio.TimeoutError, TimeoutError):
            self.logger.error("friday_shutdown_timeout", extra={"timeout": self.settings.shutdown_timeout_seconds})
        finally:
            shutdown_logging()

    async def _perform_shutdown(self) -> None:
        await self.terminal_ui.stop()
        await self.supervisor.stop()
        await self.ollama_client.aclose()
        await self.model_manager.stop()
        await self.event_bus.publish(Event.create(EventType.SYSTEM_STOPPED, {}, "app"))
        await self.event_bus.drain()
        await self.event_bus.stop()

    async def _handle_shutdown(self, _: Event) -> None:
        self._shutdown_event.set()


async def run_app() -> None:
    app = FridayApp()
    await app.run()

