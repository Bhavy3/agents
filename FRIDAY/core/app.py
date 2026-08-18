from __future__ import annotations

import asyncio
import contextlib
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
from core.llm.stream_aggregator import ResponseAggregator
from core.llm.streaming_worker import StreamingLlmWorker
from core.router.llm_fallback import LlmFallbackRouter
from core.memory.command_history import CommandHistory
from core.recovery.healthcheck import HealthcheckWorker
from core.recovery.recovery_manager import RecoveryManager
from core.router.intent_router import IntentRouter
from core.memory.memory_worker import MemoryWorker
from core.vision.screen_capture import ScreenCaptureWorker
from core.vision.ocr_worker import OCRWorker
from core.vision.window_monitor import WindowMonitorWorker
from core.vision.visual_context import VisualContextManager
from core.validation.runtime_validator import RuntimeValidationReport, RuntimeValidator, ValidationCrashWorker
from core.personality.personality_worker import PersonalityWorker
from core.workflows.workflow_worker import WorkflowWorker
from core.workflows.prompt_planner import PromptPlanner
from core.workers.supervisor import WorkerSupervisor
from interfaces.cli.health_dashboard import TerminalHealthDashboard
from interfaces.cli.terminal_ui import TerminalUI


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
        
        from core.llm.local_llm_client import create_llm_client
        self.ollama_client = create_llm_client(
            base_url=self.settings.ollama_base_url,
            model=self.settings.ollama_model,
            timeout_seconds=self.settings.ollama_timeout_seconds,
            max_retries=self.settings.ollama_max_retries,
            provider=self.settings.llm_provider,
        )
        self.stream_aggregator = ResponseAggregator(self.event_bus, metrics=self.metrics)
        self.streaming_worker = StreamingLlmWorker(
            self.event_bus, self.ollama_client, self.stream_aggregator
        )
        self.tool_worker = ToolWorker(self.event_bus, metrics=self.metrics)
        valid_tools = self.tool_worker.registry.list_tools()
        self.llm_fallback = LlmFallbackRouter(
            ollama_client=self.ollama_client,
            command_history=self.command_history,
            event_bus=self.event_bus,
            streaming_worker=self.streaming_worker,
            valid_tools=valid_tools,
        )
        self.intent_router = IntentRouter(self.event_bus, llm_fallback=self.llm_fallback)
        self.memory_worker = MemoryWorker(self.event_bus, metrics=self.metrics)
        self.screen_capture = ScreenCaptureWorker(self.event_bus, metrics=self.metrics)
        self.ocr_worker = OCRWorker(self.event_bus, metrics=self.metrics)
        self.window_monitor = WindowMonitorWorker(self.event_bus)
        self.visual_context = VisualContextManager(self.event_bus)
        self.visual_context.start()
        self.personality_worker = PersonalityWorker(self.event_bus)
        self.workflow_worker = WorkflowWorker(self.event_bus)
        self.prompt_planner = PromptPlanner(self.ollama_client)
        self.recovery_manager = RecoveryManager(self.event_bus)
        healthcheck_interval = max(1.0, min(30.0, self.settings.worker_heartbeat_timeout_seconds / 3))
        from core.audio.transport import AudioTransportWorker
        from core.audio.vad import VadWorker
        from core.audio.stt import SttWorker
        from core.audio.tts import TtsWorker
        from core.orchestrator.conversation import OrchestratorWorker
        
        orchestrator = OrchestratorWorker(
            self.event_bus,
            self.intent_router,
            self.streaming_worker,
            prompt_planner=self.prompt_planner,
            response_timeout_seconds=self.settings.ollama_timeout_seconds,
        )
        
        tts_worker = TtsWorker(
            self.event_bus,
            model_path=self.settings.tts_model_path,
            config_path=self.settings.tts_config_path,
        )
        
        self.supervisor = WorkerSupervisor(
            self.event_bus,
            workers=[
                HealthcheckWorker(self.event_bus, interval_seconds=healthcheck_interval),
                AudioTransportWorker(self.event_bus),
                VadWorker(self.event_bus),
                SttWorker(self.event_bus),
                orchestrator,
                tts_worker,
                self.tool_worker,
                self.personality_worker,
                self.workflow_worker,
                self.memory_worker,
                self.screen_capture,
                self.ocr_worker,
                self.window_monitor,
            ],
            metrics=self.metrics,
            heartbeat_timeout_seconds=self.settings.worker_heartbeat_timeout_seconds,
            max_restarts_per_minute=self.settings.max_restarts_per_minute,
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
        await self.event_bus.publish(Event.create(EventType.SYSTEM_STOPPED, {}, "app"))
        await self.event_bus.drain()
        await self.event_bus.stop()

    async def _handle_shutdown(self, _: Event) -> None:
        self._shutdown_event.set()


async def run_app() -> None:
    app = FridayApp()
    await app.run()

