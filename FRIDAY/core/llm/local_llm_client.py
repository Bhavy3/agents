from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from urllib.parse import urlparse

import httpx
from core.logging.logger import get_logger


class LlmProvider(StrEnum):
    OLLAMA = "ollama"
    LLAMACPP = "llamacpp"


@dataclass(slots=True, frozen=True)
class LlmResponse:
    intent: str
    confidence: float
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
    text = raw_text.strip()
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
        import re
        intent_match = re.search(r'"intent"\s*:\s*"([^"]+)"', text)
        confidence_match = re.search(r'"confidence"\s*:\s*([\d\.]+)', text)
        if intent_match and confidence_match:
            try:
                return LlmResponse(
                    intent=intent_match.group(1),
                    confidence=float(confidence_match.group(1)),
                    suggested_action="",
                    reasoning_summary="[Truncated]"
                )
            except ValueError:
                pass
        return None

    if not isinstance(data, dict):
        return None

    required = {"intent", "confidence"}
    if not required.issubset(data.keys()):
        return None

    try:
        return LlmResponse(
            intent=str(data["intent"]),
            confidence=float(data["confidence"]),
            suggested_action=str(data.get("suggested_action", "")),
            reasoning_summary=str(data.get("reasoning_summary", "")),
        )
    except (TypeError, ValueError):
        return None


def resolve_llm_provider(base_url: str, explicit: str | None = None) -> LlmProvider:
    if explicit:
        value = explicit.strip().lower()
        if value in {"ollama", "llamacpp", "llama_cpp", "llama.cpp"}:
            return LlmProvider.OLLAMA if value == "ollama" else LlmProvider.LLAMACPP
    if ":11434" in base_url or "localhost:11434" in base_url:
        return LlmProvider.OLLAMA
    return LlmProvider.LLAMACPP


class LocalLLMClient:
    """Local LLM HTTP client — llama.cpp (OpenAI API) or Ollama (/api/*)."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8080",
        model: str = "local",
        timeout_seconds: float = 120.0,
        max_retries: int = 2,
        temperature: float = 0.7,
        max_tokens: int = 200,
        provider: LlmProvider | str | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.provider = (
            provider
            if isinstance(provider, LlmProvider)
            else resolve_llm_provider(self.base_url, str(provider) if provider else None)
        )
        self.logger = get_logger("llm.local")
        self._available: bool | None = None
        self._client: httpx.AsyncClient | None = None
        self._last_health_check: float = 0.0
        self._health_check_ttl: float = 30.0
        parsed = urlparse(self.base_url)
        self._host = parsed.hostname or "127.0.0.1"
        self._port = parsed.port or (11434 if self.provider == LlmProvider.OLLAMA else 8080)

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self.timeout_seconds)
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _chat_completions_url(self) -> str:
        return f"{self.base_url}/v1/chat/completions"

    def _ollama_generate_url(self) -> str:
        return f"{self.base_url}/api/generate"

    def _chat_payload(self, prompt: str, *, stream: bool, max_tokens_override: int | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "messages": [{"role": "user", "content": prompt}],
            "temperature": self.temperature,
            "max_tokens": max_tokens_override if max_tokens_override is not None else self.max_tokens,
            "stream": stream,
        }
        if self.model:
            payload["model"] = self.model
        return payload

    def _ollama_payload(self, prompt: str, *, stream: bool, max_tokens_override: int | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "stream": stream,
        }
        if max_tokens_override is not None:
            payload["options"] = {"num_predict": max_tokens_override}
        return payload

    async def health_check(self) -> bool:
        if self._available and (time.perf_counter() - self._last_health_check) < self._health_check_ttl:
            return True
            
        try:
            client = self._get_client()
            if self.provider == LlmProvider.LLAMACPP:
                health_url = f"{self.base_url.rstrip('/')}/health"
                response = await client.get(health_url, timeout=3.0)
                self._available = (response.status_code == 200)
            else:  # OLLAMA
                version_url = f"{self.base_url.rstrip('/')}/api/version"
                try:
                    response = await client.get(version_url, timeout=3.0)
                    if response.status_code == 200:
                        self._available = True
                except Exception as e:
                    self.logger.debug("ollama_version_check_failed", extra={"error": str(e)})
                if not self._available:
                    tags_url = f"{self.base_url.rstrip('/')}/api/tags"
                    response = await client.get(tags_url, timeout=3.0)
                    self._available = (response.status_code == 200)
        except Exception as e:
            print(f"\n[DIAGNOSTIC] health_check threw exception: {repr(e)}")
            self._available = False

        if self._available:
            self._last_health_check = time.perf_counter()

        self.logger.info(
            "llm_health_check",
            extra={
                "available": self._available,
                "provider": self.provider.value,
                "model": self.model,
                "base_url": self.base_url,
            },
        )
        return bool(self._available)

    async def generate(self, prompt: str, max_tokens: int | None = None) -> tuple[str | None, LlmRequestMetrics]:
        started = time.perf_counter()
        last_error: str | None = None
        endpoint = (
            self._chat_completions_url()
            if self.provider == LlmProvider.LLAMACPP
            else self._ollama_generate_url()
        )
        self.logger.info(
            "llm_generate_request_started",
            extra={
                "provider": self.provider.value,
                "endpoint": endpoint,
                "model": self.model,
                "prompt_length": len(prompt),
                "stream": False,
            },
        )

        client = self._get_client()
        for attempt in range(1, self.max_retries + 1):
            try:
                if not await self._ensure_available(attempt):
                    last_error = "llm_unavailable"
                    await asyncio.sleep(min(0.25 * attempt, 1.0))
                    continue

                if self.provider == LlmProvider.LLAMACPP:
                    payload = self._chat_payload(prompt, stream=False, max_tokens_override=max_tokens)
                    response = await client.post(
                        endpoint,
                        json=payload,
                        headers={"Content-Type": "application/json"},
                        timeout=self.timeout_seconds
                    )
                    if response.status_code == 200:
                        data = response.json()
                        raw = self._extract_message_content(data)
                    else:
                        raw = None
                        last_error = f"HTTP status {response.status_code}"
                else:
                    payload = self._ollama_payload(prompt, stream=False, max_tokens_override=max_tokens)
                    response = await client.post(
                        endpoint,
                        json=payload,
                        headers={"Content-Type": "application/json"},
                        timeout=self.timeout_seconds
                    )
                    if response.status_code == 200:
                        data = response.json()
                        raw = str(data.get("response", "")) or None
                    else:
                        raw = None
                        last_error = f"HTTP status {response.status_code}"

                latency = time.perf_counter() - started
                valid, validation_error = self._validate_generated_text(raw)
                if valid and raw is not None:
                    self.logger.info(
                        "llm_generate_success",
                        extra={
                            "provider": self.provider.value,
                            "model": self.model,
                            "latency": round(latency, 3),
                            "attempt": attempt,
                            "response_length": len(raw),
                        },
                    )
                    return raw, LlmRequestMetrics(
                        latency_seconds=latency,
                        model=self.model,
                        success=True,
                        response_tokens=len(raw.split()),
                    )
                last_error = validation_error or last_error or "empty response from LLM"
            except asyncio.CancelledError:
                raise
            except (asyncio.TimeoutError, TimeoutError, httpx.TimeoutException):
                last_error = f"timeout after {self.timeout_seconds}s"
            except Exception as e:
                last_error = str(e)

        latency = time.perf_counter() - started
        self.logger.error(
            "llm_generate_failed",
            extra={
                "provider": self.provider.value,
                "model": self.model,
                "retries": self.max_retries,
                "error": last_error,
            },
        )
        return None, LlmRequestMetrics(
            latency_seconds=latency, model=self.model, success=False, error=last_error
        )

    def _extract_message_content(self, data: dict[str, Any]) -> str | None:
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            return None
        first = choices[0]
        if not isinstance(first, dict):
            return None
        message = first.get("message")
        if isinstance(message, dict):
            content = message.get("content")
            return str(content) if content is not None else None
        delta = first.get("delta")
        if isinstance(delta, dict):
            content = delta.get("content")
            return str(content) if content is not None else ""
        return None

    async def stream_generate(self, prompt: str):
        started = time.perf_counter()
        endpoint = (
            self._chat_completions_url()
            if self.provider == LlmProvider.LLAMACPP
            else self._ollama_generate_url()
        )
        payload = (
            self._chat_payload(prompt, stream=True)
            if self.provider == LlmProvider.LLAMACPP
            else self._ollama_payload(prompt, stream=True)
        )

        client = self._get_client()
        try:
            async with client.stream(
                "POST",
                endpoint,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=self.timeout_seconds,
            ) as response:
                if response.status_code != 200:
                    self.logger.warning(
                        "llm_stream_failed_status",
                        extra={"status": response.status_code},
                    )
                    return

                async for line in response.aiter_lines():
                    if not line:
                        continue
                    
                    if self.provider == LlmProvider.LLAMACPP:
                        parsed = self._parse_chat_stream_line(line.strip())
                    else:
                        parsed = self._parse_legacy_ollama_line(line.strip())
                        
                    if parsed is None:
                        continue
                    
                    chunk, done = parsed
                    yield chunk, done
                    if done:
                        break
        except asyncio.CancelledError:
            # Close client on cancellation to prevent resource leaks
            if self._client:
                await self._client.aclose()
                self._client = None
            raise
        except (httpx.RemoteProtocolError, httpx.LocalProtocolError, httpx.ConnectError) as e:
            # Close and recreate client on protocol/connection errors that indicate corruption
            # Normal errors keep client alive for connection reuse
            self.logger.warning("llm_client_corrupted_closing", extra={"error": str(e)})
            if self._client:
                await self._client.aclose()
                self._client = None
            raise
        except Exception as e:
            self.logger.warning("llm_generate_exception", extra={"error": str(e)})
        finally:
            self.logger.info(
                "llm_stream_complete",
                extra={"latency_ms": round((time.perf_counter() - started) * 1000, 3)},
            )

    def _parse_chat_stream_line(self, line: str) -> tuple[str, bool] | None:
        if not line.startswith("data:"):
            return None
        payload = line[5:].strip()
        if payload == "[DONE]":
            return "", True
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            return None
        if not isinstance(data, dict):
            return None
        content = self._extract_message_content(data) or ""
        finish = False
        choices = data.get("choices")
        if isinstance(choices, list) and choices and isinstance(choices[0], dict):
            finish = choices[0].get("finish_reason") is not None
        return content, finish

    def _parse_generate_stream_line(self, line: str) -> tuple[str, bool] | None:
        if line.startswith("data:"):
            return self._parse_chat_stream_line(line)
        return self._parse_legacy_ollama_line(line)

    def _parse_legacy_ollama_line(self, line: str) -> tuple[str, bool] | None:
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            return None
        if not isinstance(data, dict):
            return None
        return str(data.get("response", "")), bool(data.get("done", False))

    async def _ensure_available(self, attempt: int) -> bool:
        if await self.health_check():
            return True
        self.logger.warning(
            "llm_unavailable_before_generate",
            extra={
                "provider": self.provider.value,
                "model": self.model,
                "attempt": attempt,
                "base_url": self.base_url,
            },
        )
        return False

    def _validate_generated_text(self, text: object) -> tuple[bool, str | None]:
        if not isinstance(text, str):
            return False, "response_not_string"
        if not text.strip():
            return False, "response_empty"
        return True, None

    async def completion(self, prompt: str) -> str:
        full_response = ""
        async for chunk, done in self.stream_generate(prompt):
            if chunk:
                full_response += chunk
            if done:
                break
        return full_response.strip()

    async def chat(self, messages: list[dict[str, str]]) -> str:
        prompt = "\n".join(
            f"{message.get('role', 'user')}: {message.get('content', '')}" for message in messages
        )
        return await self.completion(prompt)


def create_llm_client(
    base_url: str,
    model: str,
    timeout_seconds: float,
    max_retries: int,
    provider: str | None = None,
) -> LocalLLMClient:
    resolved = resolve_llm_provider(base_url, provider)
    return LocalLLMClient(
        base_url=base_url,
        model=model,
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
        provider=resolved,
    )


# Backward-compatible alias used across FRIDAY
OllamaClient = LocalLLMClient
