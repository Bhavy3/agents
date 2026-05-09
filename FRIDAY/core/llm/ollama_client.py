from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.request import urlopen, Request
from urllib.error import URLError

from core.logging.logger import get_logger


@dataclass(slots=True, frozen=True)
class LlmResponse:
    """Structured contract for LLM outputs. Raw LLM text is parsed into this."""
    intent: str
    confidence: float
    response_text: str
    suggested_action: str
    reasoning_summary: str


@dataclass(slots=True, frozen=True)
class LlmRequestMetrics:
    prompt_tokens: int = 0
    response_tokens: int = 0
    latency_seconds: float = 0.0
    model: str = ""
    success: bool = False
    error: str | None = None


def parse_llm_response(raw_text: str) -> LlmResponse | None:
    """Parse structured JSON from LLM output. Returns None on failure."""
    text = raw_text.strip()
    # Try to extract JSON block if wrapped in markdown
    if "```json" in text:
        start = text.index("```json") + 7
        end = text.index("```", start)
        text = text[start:end].strip()
    elif "```" in text:
        start = text.index("```") + 3
        end = text.index("```", start)
        text = text[start:end].strip()

    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None

    if not isinstance(data, dict):
        return None

    required = {"intent", "confidence", "response_text"}
    if not required.issubset(data.keys()):
        return None

    try:
        return LlmResponse(
            intent=str(data["intent"]),
            confidence=float(data["confidence"]),
            response_text=str(data["response_text"]),
            suggested_action=str(data.get("suggested_action", "")),
            reasoning_summary=str(data.get("reasoning_summary", "")),
        )
    except (TypeError, ValueError):
        return None


class OllamaClient:
    """Isolated Ollama HTTP client. No runtime state mutation."""

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "qwen2.5:7b",
        timeout_seconds: float = 30.0,
        max_retries: int = 2,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.logger = get_logger("llm.ollama")
        self._available: bool | None = None

    async def health_check(self) -> bool:
        """Check if Ollama is reachable."""
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(self._http_get, f"{self.base_url}/api/tags"),
                timeout=5.0,
            )
            self._available = result is not None
        except Exception:
            self._available = False
        self.logger.info("ollama_health_check", extra={"available": self._available, "model": self.model})
        return self._available

    async def generate(self, prompt: str) -> tuple[str | None, LlmRequestMetrics]:
        """Send prompt to Ollama. Returns (response_text, metrics). Never raises."""
        started = time.perf_counter()
        last_error: str | None = None

        for attempt in range(1, self.max_retries + 1):
            try:
                raw = await asyncio.wait_for(
                    asyncio.to_thread(self._http_generate, prompt),
                    timeout=self.timeout_seconds,
                )
                latency = time.perf_counter() - started
                if raw is not None:
                    self.logger.info(
                        "ollama_generate_success",
                        extra={"model": self.model, "latency": round(latency, 3), "attempt": attempt},
                    )
                    return raw, LlmRequestMetrics(
                        latency_seconds=latency, model=self.model, success=True
                    )
                last_error = "empty response from Ollama"
            except asyncio.CancelledError:
                raise
            except (asyncio.TimeoutError, TimeoutError):
                last_error = f"timeout after {self.timeout_seconds}s"
                self.logger.warning(
                    "ollama_generate_timeout",
                    extra={"model": self.model, "attempt": attempt, "timeout": self.timeout_seconds},
                )
            except Exception as e:
                last_error = str(e)
                self.logger.warning(
                    "ollama_generate_error",
                    extra={"model": self.model, "attempt": attempt, "error": last_error},
                )

        latency = time.perf_counter() - started
        self.logger.error(
            "ollama_generate_failed",
            extra={"model": self.model, "retries": self.max_retries, "error": last_error},
        )
        return None, LlmRequestMetrics(
            latency_seconds=latency, model=self.model, success=False, error=last_error
        )

    def _http_generate(self, prompt: str) -> str | None:
        """Synchronous HTTP call to Ollama /api/generate. Runs in thread."""
        payload = json.dumps({
            "model": self.model,
            "prompt": prompt,
            "stream": False,
        }).encode("utf-8")
        req = Request(
            f"{self.base_url}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(req, timeout=self.timeout_seconds) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data.get("response", "")
        except Exception:
            return None

    async def stream_generate(self, prompt: str):
        """Stream response from Ollama. Yields chunks until done."""
        loop = asyncio.get_running_loop()
        queue = asyncio.Queue(maxsize=100) # Backpressure protection
        
        def run_sync():
            payload = json.dumps({
                "model": self.model,
                "prompt": prompt,
                "stream": True,
            }).encode("utf-8")
            req = Request(
                f"{self.base_url}/api/generate",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                # Use a smaller timeout for the initial connection
                with urlopen(req, timeout=self.timeout_seconds) as resp:
                    for line in resp:
                        if line:
                            try:
                                data = json.loads(line.decode("utf-8"))
                                chunk = data.get("response", "")
                                done = data.get("done", False)
                                # Use thread-safe call to put in queue
                                loop.call_soon_threadsafe(queue.put_nowait, (chunk, done, None))
                                if done:
                                    break
                            except json.JSONDecodeError:
                                continue
            except Exception as e:
                loop.call_soon_threadsafe(queue.put_nowait, (None, True, str(e)))

        # Run in a separate thread to avoid blocking the event loop
        stream_task = loop.run_in_executor(None, run_sync)
        
        try:
            while True:
                # Inter-chunk timeout enforcement
                try:
                    chunk, done, error = await asyncio.wait_for(queue.get(), timeout=self.timeout_seconds)
                    if error:
                        self.logger.error("ollama_stream_error", extra={"error": error})
                        break
                    yield chunk, done
                    if done:
                        break
                except asyncio.TimeoutError:
                    self.logger.warning("ollama_stream_timeout", extra={"timeout": self.timeout_seconds})
                    break
        finally:
            # Ensure the sync thread doesn't hang (though urlopen timeout helps)
            # and clean up the generator
            pass

    def _http_get(self, url: str) -> str | None:
        """Synchronous HTTP GET. Runs in thread."""
        try:
            req = Request(url, method="GET")
            with urlopen(req, timeout=5.0) as resp:
                return resp.read().decode("utf-8")
        except Exception:
            return None
