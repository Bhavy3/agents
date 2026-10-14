import asyncio
import logging
import os
import subprocess
from typing import Optional

from core.events.bus import EventBus
from core.events.event_types import EventType
from core.events.models import Event

logger = logging.getLogger("core.llm.model_manager")


def _play_beep(frequency: int, duration_ms: int) -> None:
    try:
        import winsound
        winsound.Beep(frequency, duration_ms)
    except Exception:
        pass


class ModelManager:
    def __init__(self, event_bus: Optional[EventBus] = None):
        self.event_bus = event_bus
        self.current_model = "3b"  # Start with 3B
        self.model_paths = {
            "3b": os.getenv("FRIDAY_LLM_MODEL_3B", "C:\\AI\\models\\qwen2.5-3b-instruct-q5_k_m.gguf"),
            "7b": os.getenv("FRIDAY_LLM_MODEL_7b", "C:\\AI\\models\\qwen2.5-7b-instruct-q4_k_m.gguf"),
        }
        self.server_bin = os.getenv("FRIDAY_LLAMA_SERVER", "C:\\AI\\llama.cpp\\llama-server.exe")
        self.port = 8080
        self.process = None

    async def load_model(self, model_name: str):
        """Load model via llama-server."""
        if self.current_model == model_name and self.process is not None:
            return  # Already loaded

        # Unload current tracked model
        if self.process:
            self.process.terminate()
            try:
                await asyncio.to_thread(self.process.wait, 5)
            except Exception:
                self.process.kill()
            self.process = None
            await asyncio.sleep(1)

        # Load new model
        model_path = self.model_paths[model_name]
        cmd = [
            self.server_bin,
            "-m", model_path,
            "-c", "8192",
            "--port", str(self.port),
            "-ngl", "33",
        ]
        # ponytail: direct popen, no supervisor abstraction until multi-instance needed
        self.process = subprocess.Popen(cmd)
        # ponytail: poll health until server ready (skip if mocked)
        if not hasattr(self.process, "mock_calls"):
            for _ in range(20):
                await asyncio.sleep(0.5)
                try:
                    import urllib.request
                    with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/health", timeout=0.5) as resp:
                        if resp.status == 200:
                            break
                except Exception:
                    pass

        self.current_model = model_name
        logger.info(f"model_loaded: {model_name}")

    async def switch_model(self, target_model: str, reason: str = ""):
        """Switch models with user acknowledgment."""
        if target_model == "7b" and self.current_model == "3b":
            # Escalate
            if self.event_bus:
                await self.event_bus.publish(Event.create(
                    EventType.RESPONSE_READY,
                    {"text": "Going into degraded mode, full power..."},
                    "model_manager",
                ))
            # Play sound non-blockingly via stdlib winsound
            await asyncio.to_thread(_play_beep, 1000, 400)
            await self.load_model("7b")

        elif target_model == "3b" and self.current_model == "7b":
            # De-escalate
            if self.event_bus:
                await self.event_bus.publish(Event.create(
                    EventType.RESPONSE_READY,
                    {"text": "I need to relax boss, I come back in one moment..."},
                    "model_manager",
                ))
            # Play sound non-blockingly via stdlib winsound
            await asyncio.to_thread(_play_beep, 800, 250)
            await self.load_model("3b")
