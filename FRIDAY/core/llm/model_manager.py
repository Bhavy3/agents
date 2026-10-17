import asyncio
import logging
import os
import subprocess
import urllib.request
from pathlib import Path
from typing import Optional

from core.events.bus import EventBus
from core.events.event_types import EventType
from core.events.models import Event

logger = logging.getLogger("core.llm.model_manager")


class ModelLaunchError(RuntimeError):
    """Raised internally when a llama-server target cannot be made healthy."""


def _play_beep(frequency: int, duration_ms: int) -> None:
    try:
        os.system(f"powershell -c [console]::beep({frequency}, {duration_ms})")
    except Exception:
        logger.exception(
            "model_acknowledgment_beep_failed",
            extra={"frequency": frequency, "duration_ms": duration_ms},
        )


class ModelManager:
    def __init__(
        self,
        event_bus: Optional[EventBus] = None,
        *,
        gpu_layers: int | None = None,
        health_timeout_seconds: float | None = None,
        health_poll_interval_seconds: float | None = None,
        port: int | None = None,
    ):
        self.event_bus = event_bus
        self.current_model = "3b"  # Start with 3B
        self.model_paths = {
            "3b": os.getenv(
                "FRIDAY_LLM_MODEL_3B",
                os.getenv("FRIDAY_LLM_MODEL_3b", "C:\\AI\\models\\qwen2.5-3b-instruct-q5_k_m.gguf"),
            ),
            "7b": os.getenv(
                "FRIDAY_LLM_MODEL_7B",
                os.getenv("FRIDAY_LLM_MODEL_7b", "C:\\AI\\models\\qwen2.5-7b-instruct-q4_k_m.gguf"),
            ),
        }
        self.server_bin = os.getenv("FRIDAY_LLAMA_SERVER", "C:\\AI\\llama.cpp\\llama-server.exe")
        self.port = port if port is not None else int(os.getenv("FRIDAY_LLAMA_PORT", "8080"))
        self.gpu_layers = self._nonnegative_int(
            gpu_layers,
            self._first_env(
                "FRIDAY_LLAMA_NGL",
                "FRIDAY_LLAMA_GPU_LAYERS",
                "FRIDAY_LLM_GPU_LAYERS",
                "FRIDAY_GPU_LAYERS",
            ),
            default=0,
            setting="gpu layers",
        )
        self.health_timeout_seconds = self._positive_float(
            health_timeout_seconds,
            self._first_env("FRIDAY_LLAMA_HEALTH_TIMEOUT_SECONDS", "FRIDAY_LLAMA_HEALTH_TIMEOUT"),
            default=10.0,
            setting="health timeout",
        )
        self.health_poll_interval_seconds = self._positive_float(
            health_poll_interval_seconds,
            self._first_env("FRIDAY_LLAMA_HEALTH_POLL_INTERVAL_SECONDS", "FRIDAY_LLAMA_HEALTH_POLL_INTERVAL"),
            default=0.5,
            setting="health poll interval",
        )
        self.process = None

    @staticmethod
    def _first_env(*names: str) -> str | None:
        for name in names:
            value = os.getenv(name)
            if value is not None and value.strip():
                return value
        return None

    @staticmethod
    def _nonnegative_int(
        explicit: int | None,
        configured: str | None,
        *,
        default: int,
        setting: str,
    ) -> int:
        value = explicit if explicit is not None else configured
        if value is None:
            return default
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            logger.warning("invalid_model_manager_setting", extra={"setting": setting, "value": value, "default": default})
            return default
        if parsed < 0:
            logger.warning("invalid_model_manager_setting", extra={"setting": setting, "value": value, "default": default})
            return default
        return parsed

    @staticmethod
    def _positive_float(
        explicit: float | None,
        configured: str | None,
        *,
        default: float,
        setting: str,
    ) -> float:
        value = explicit if explicit is not None else configured
        if value is None:
            return default
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            logger.warning("invalid_model_manager_setting", extra={"setting": setting, "value": value, "default": default})
            return default
        if parsed <= 0:
            logger.warning("invalid_model_manager_setting", extra={"setting": setting, "value": value, "default": default})
            return default
        return parsed

    def _validated_command(self, model_name: str) -> list[str]:
        try:
            model_path = Path(self.model_paths[model_name]).expanduser()
        except (KeyError, TypeError, ValueError) as exc:
            raise ModelLaunchError(f"unknown or invalid model path for {model_name!r}") from exc

        server_path = Path(self.server_bin).expanduser()
        missing = []
        if not server_path.is_file():
            missing.append(f"server executable {server_path}")
        if not model_path.is_file():
            missing.append(f"model file {model_path}")
        if missing:
            raise ModelLaunchError("missing launch path(s): " + "; ".join(missing))

        return [
            str(server_path),
            "-m", str(model_path),
            "-c", "8192",
            "--port", str(self.port),
            "-ngl", str(self.gpu_layers),
        ]

    async def _stop_process(self, process: object | None) -> None:
        if process is None:
            return
        try:
            process.terminate()
        except Exception:
            logger.warning("model_process_terminate_failed", exc_info=True)
        try:
            await asyncio.to_thread(process.wait, 5)
        except Exception:
            try:
                process.kill()
                await asyncio.to_thread(process.wait, 1)
            except Exception:
                logger.warning("model_process_kill_failed", exc_info=True)

    async def _wait_for_health(self) -> bool:
        """Wait until the target endpoint explicitly reports HTTP 200."""
        health_url = f"http://127.0.0.1:{self.port}/health"
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.health_timeout_seconds
        while True:
            remaining = deadline - loop.time()
            request_timeout = max(0.01, min(0.5, remaining))
            try:
                with urllib.request.urlopen(health_url, timeout=request_timeout) as response:
                    if response.status == 200:
                        return True
            except Exception:
                pass

            if loop.time() >= deadline:
                return False
            await asyncio.sleep(min(self.health_poll_interval_seconds, deadline - loop.time()))

    async def _start_healthy_process(self, model_name: str) -> tuple[object | None, str | None]:
        try:
            command = self._validated_command(model_name)
            process = subprocess.Popen(command)
        except (ModelLaunchError, OSError, subprocess.SubprocessError) as exc:
            return None, str(exc)

        try:
            healthy = await self._wait_for_health()
        except Exception as exc:
            healthy = False
            health_error = f"health check raised {exc!r}"
        else:
            health_error = "health endpoint did not return HTTP 200 before deadline"

        if not healthy:
            await self._stop_process(process)
            return None, health_error
        return process, None

    async def _emit_load_failure(
        self,
        *,
        target_model: str,
        previous_model: str,
        error: str,
        rolled_back: bool,
    ) -> None:
        message = f"model startup failed for {target_model}: {error}"
        logger.error(
            "model_switch_failed",
            extra={
                "target_model": target_model,
                "previous_model": previous_model,
                "rolled_back": rolled_back,
                "error": error,
            },
        )
        if self.event_bus is None:
            return
        try:
            await self.event_bus.publish(
                Event.create(
                    EventType.LLM_FAILURE,
                    {
                        "error": message,
                        "model": target_model,
                        "target_model": target_model,
                        "previous_model": previous_model,
                        "rolled_back": rolled_back,
                    },
                    "model_manager",
                )
            )
        except RuntimeError:
            logger.warning("model_switch_failure_event_not_published", extra={"error": message})

    async def load_model(self, model_name: str) -> bool:
        """Load a model and report success only after an HTTP 200 health check."""
        if self.current_model == model_name and self.process is not None:
            return True  # Already loaded

        previous_model = self.current_model
        previous_process = self.process

        # Validate before stopping the current server so a bad path cannot destroy
        # a healthy local/free model that is already serving requests.
        try:
            self._validated_command(model_name)
        except ModelLaunchError as exc:
            await self._emit_load_failure(
                target_model=model_name,
                previous_model=previous_model,
                error=str(exc),
                rolled_back=previous_process is not None,
            )
            return False

        # Unload current tracked model
        await self._stop_process(previous_process)
        self.process = None

        new_process, error = await self._start_healthy_process(model_name)
        if new_process is not None:
            self.process = new_process
            self.current_model = model_name
            logger.info("model_loaded", extra={"model": model_name, "gpu_layers": self.gpu_layers})
            return True

        # The target is never made active after a failed health check. Restore
        # the prior model on the same port when there was a prior process to
        # replace; this also gives callers a usable local fallback.
        rollback_process = None
        rollback_error = None
        if previous_process is not None:
            rollback_process, rollback_error = await self._start_healthy_process(previous_model)
        if rollback_process is not None:
            self.process = rollback_process
            self.current_model = previous_model
            rolled_back = True
        else:
            self.process = None
            self.current_model = previous_model
            rolled_back = False
            if rollback_error:
                error = f"{error}; rollback failed: {rollback_error}"

        await self._emit_load_failure(
            target_model=model_name,
            previous_model=previous_model,
            error=error or "unknown startup failure",
            rolled_back=rolled_back,
        )
        return False

    async def switch_model(self, target_model: str, reason: str = "") -> bool:
        """Switch models with user acknowledgment after a healthy startup."""
        if target_model == "7b" and self.current_model == "3b":
            # Escalate
            # Preserve the Windows acknowledgment-beep command contract without blocking.
            await asyncio.to_thread(_play_beep, 1000, 500)
            loaded = await self.load_model("7b")
            if loaded and self.event_bus:
                await self.event_bus.publish(Event.create(
                    EventType.RESPONSE_READY,
                    {"text": "Going into degraded mode, full power..."},
                    "model_manager",
                ))
            return loaded

        elif target_model == "3b" and self.current_model == "7b":
            # De-escalate
            # Preserve the Windows acknowledgment-beep command contract without blocking.
            await asyncio.to_thread(_play_beep, 800, 250)
            loaded = await self.load_model("3b")
            if loaded and self.event_bus:
                await self.event_bus.publish(Event.create(
                    EventType.RESPONSE_READY,
                    {"text": "I need to relax boss, I come back in one moment..."},
                    "model_manager",
                ))
            return loaded

        return target_model == self.current_model
