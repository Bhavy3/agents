import asyncio
import logging
import os
import subprocess
import urllib.request
from inspect import isawaitable
from pathlib import Path
from typing import Any, Optional

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
        client: Any | None = None,
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
        self.client = client
        configured_port = port if port is not None else int(os.getenv("FRIDAY_LLAMA_PORT", "8080"))
        self.port = configured_port
        # Keep the existing 3B endpoint alive and use a separate endpoint for
        # 7B.  This makes automatic switching real instead of changing only a
        # label in the request payload.
        self.model_ports = {
            "3b": configured_port,
            "7b": int(os.getenv("FRIDAY_LLAMA_7B_PORT", "8081")) if port is None else port,
        }
        self.model_base_urls = {
            "3b": os.getenv("FRIDAY_LLM_BASE_URL_3B", f"http://127.0.0.1:{self.model_ports['3b']}"),
            "7b": os.getenv("FRIDAY_LLM_BASE_URL_7B", f"http://127.0.0.1:{self.model_ports['7b']}"),
        }
        self.gpu_layers = self._nonnegative_int(
            gpu_layers,
            self._first_env(
                "FRIDAY_LLAMA_NGL",
                "FRIDAY_LLAMA_GPU_LAYERS",
                "FRIDAY_LLM_GPU_LAYERS",
                "FRIDAY_GPU_LAYERS",
            ),
            default=33,
            setting="gpu layers",
        )
        self.model_gpu_layers = {
            "3b": self.gpu_layers,
            # Q4 7B does not fit the current default 33-layer offload. Keep
            # the 3B setting untouched and use a safe per-model default;
            # callers can opt into a measured 7B offload explicitly.
            "7b": self._nonnegative_int(
                None,
                self._first_env(
                    "FRIDAY_LLAMA_NGL_7B",
                    "FRIDAY_LLAMA_7B_GPU_LAYERS",
                    "FRIDAY_LLAMA_NGL",
                    "FRIDAY_LLAMA_GPU_LAYERS",
                    "FRIDAY_LLM_GPU_LAYERS",
                    "FRIDAY_GPU_LAYERS",
                ),
                default=0,
                setting="7B gpu layers",
            ),
        }
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
        self.model_health_timeouts = {
            "3b": self.health_timeout_seconds,
            "7b": self._positive_float(
                None,
                self._first_env("FRIDAY_LLAMA_7B_HEALTH_TIMEOUT_SECONDS"),
                default=max(self.health_timeout_seconds, 30.0),
                setting="7B health timeout",
            ),
        }
        self.process = None
        self.model_processes: dict[str, Any | None] = {"3b": None, "7b": None}
        self.model_ready: dict[str, bool] = {"3b": False, "7b": False}

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

    def _validated_command(self, model_name: str, *, port: int | None = None) -> list[str]:
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
            "--port", str(self.model_ports.get(model_name, port if port is not None else self.port)),
            "-ngl", str(self.model_gpu_layers.get(model_name, self.gpu_layers)),
        ]

    async def _stop_process(self, process: Any | None) -> None:
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

    async def _wait_for_health(
        self,
        port: int | None = None,
        base_url: str | None = None,
        timeout_seconds: float | None = None,
        expected_absent: bool = False,
    ) -> bool:
        """Wait until the target endpoint explicitly reports HTTP 200."""
        if base_url:
            health_url = f"{base_url.rstrip('/')}/health"
        elif port is not None:
            health_url = f"http://127.0.0.1:{port}/health"
        else:
            health_url = f"http://127.0.0.1:{self.port}/health"
        loop = asyncio.get_running_loop()
        health_timeout = self.health_timeout_seconds
        if base_url:
            model_name = next((name for name, url in self.model_base_urls.items() if url.rstrip("/") == base_url.rstrip("/")), None)
            health_timeout = self.model_health_timeouts.get(model_name or "", health_timeout)
        if timeout_seconds is not None:
            health_timeout = timeout_seconds
        deadline = loop.time() + health_timeout
        last_error: BaseException | None = None
        while True:
            remaining = deadline - loop.time()
            request_timeout = max(0.01, min(0.5, remaining))
            try:
                with urllib.request.urlopen(health_url, timeout=request_timeout) as response:
                    if response.status == 200:
                        return True
            except Exception as exc:
                last_error = exc

            if loop.time() >= deadline:
                if expected_absent:
                    # Pre-launch probe: no sidecar on the port yet is the normal case.
                    logger.info("sidecar_endpoint_not_running", extra={"health_url": health_url})
                else:
                    logger.warning(
                        "model_health_check_timed_out",
                        exc_info=(type(last_error), last_error, last_error.__traceback__) if last_error else None,
                        extra={"health_url": health_url},
                    )
                return False
            await asyncio.sleep(min(self.health_poll_interval_seconds, deadline - loop.time()))

    async def _start_healthy_process(self, model_name: str, *, port: int | None = None) -> tuple[object | None, str | None]:
        try:
            command = self._validated_command(model_name, port=port)
            process = subprocess.Popen(command)
        except (ModelLaunchError, OSError, subprocess.SubprocessError) as exc:
            return None, str(exc)

        try:
            healthy = await self._wait_for_health(
                port or self.model_ports.get(model_name),
                self.model_base_urls.get(model_name),
            )
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
            self.model_ready[model_name] = True
            return True  # Already loaded

        self.model_ready[model_name] = False

        if self.client is not None:
            return await self._load_endpoint_model(model_name)

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
            self.model_ready[model_name] = True
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
            self.model_ready[previous_model] = True
            rolled_back = True
        else:
            self.process = None
            self.current_model = previous_model
            self.model_ready[previous_model] = False
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

    async def _load_endpoint_model(self, model_name: str) -> bool:
        """Select a model endpoint, starting only FRIDAY-owned sidecars."""
        self.model_ready[model_name] = False
        if model_name not in self.model_paths:
            await self._emit_load_failure(
                target_model=model_name,
                previous_model=self.current_model,
                error=f"unknown model {model_name!r}",
                rolled_back=False,
            )
            return False

        target_url = self.model_base_urls[model_name]
        target_port = self.model_ports[model_name]
        # A missing sidecar should be detected quickly so startup can begin;
        # the longer model-specific timeout is reserved for the process load.
        healthy = await self._wait_for_health(target_port, target_url, timeout_seconds=1.0, expected_absent=True)
        if not healthy and model_name == "7b":
            process, error = await self._start_healthy_process(model_name, port=target_port)
            if process is not None:
                self.model_processes[model_name] = process
                healthy = True
            else:
                await self._emit_load_failure(
                    target_model=model_name,
                    previous_model=self.current_model,
                    error=error or "7B endpoint is unavailable",
                    rolled_back=True,
                )
                return False

        if not healthy:
            await self._emit_load_failure(
                target_model=model_name,
                previous_model=self.current_model,
                error=f"model endpoint is unavailable: {target_url}",
                rolled_back=False,
            )
            return False

        switcher = getattr(self.client, "use_backend", None)
        if callable(switcher):
            result = switcher(
                target_url,
                model=Path(self.model_paths[model_name]).stem,
                logical_model=model_name,
                reason=f"active_{model_name}",
            )
            if isawaitable(result):
                await result
        self.current_model = model_name
        self.process = self.model_processes.get(model_name)
        self.model_ready[model_name] = True
        logger.info("model_endpoint_selected", extra={"model": model_name, "base_url": target_url})
        return True

    async def stop(self) -> None:
        """Stop only sidecars started by FRIDAY; never stop external endpoints."""
        for model_name, process in list(self.model_processes.items()):
            if process is not None:
                await self._stop_process(process)
                self.model_processes[model_name] = None
            self.model_ready[model_name] = False
        self.process = None

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
            elif not loaded and self.event_bus:
                if self.process is not None and self.current_model == "3b":
                    message = "The 7B model could not start, so I restored the 3B model and will continue with it."
                else:
                    message = "The 7B model could not start, and the 3B model did not recover. Please restart the local model server."
                await self.event_bus.publish(Event.create(
                    EventType.RESPONSE_READY,
                    {"text": message},
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
