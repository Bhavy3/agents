from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import Any

from core.events.bus import EventBus
from core.events.event_types import EventType
from core.events.models import Event
from core.llm.ollama_client import OllamaClient
from core.llm.stream_aggregator import ResponseAggregator
from core.logging.logger import get_logger


class StreamingLlmWorker:
    """Manages LLM streaming tasks with strict cancellation and timeout safety."""

    def __init__(
        self,
        event_bus: EventBus,
        ollama_client: OllamaClient,
        aggregator: ResponseAggregator,
        timeout_seconds: float | None = None,
    ) -> None:
        self.event_bus = event_bus
        self.ollama = ollama_client
        self.aggregator = aggregator
        self.timeout_seconds = float(timeout_seconds) if timeout_seconds is not None else float(getattr(ollama_client, "timeout_seconds", 30.0))
        self.logger = get_logger("llm.streaming_worker")
        self._active_tasks: dict[str, asyncio.Task] = {}
        self.selected_model = self._initial_model()
        selection_reason = getattr(ollama_client, "selection_reason", "configured")
        self.selection_reason = selection_reason if isinstance(selection_reason, str) else "configured"

    def _initial_model(self) -> str:
        requested_model = getattr(self.ollama, "requested_model", None)
        if isinstance(requested_model, str) and requested_model:
            return requested_model
        model = getattr(self.ollama, "model", "")
        return model if isinstance(model, str) else ""

    @property
    def model(self) -> str:
        """The logical model label selected for the next stream."""
        return self.selected_model

    @property
    def active_model(self) -> str:
        return self.selected_model

    @property
    def model_reason(self) -> str:
        return self.selection_reason

    def set_model(self, model: str, reason: str = "") -> None:
        """Select the logical model for the next stream without restarting a server."""
        self.selected_model = str(model)
        self.selection_reason = str(reason)

        # LocalLLMClient exposes this explicitly so the requested label stays
        # separate from the model actually loaded by a llama.cpp endpoint.
        for setter_name in ("set_requested_model", "select_model", "set_model"):
            setter = getattr(self.ollama, setter_name, None)
            if callable(setter):
                setter(self.selected_model, self.selection_reason)
                return

        # Keep simple fake clients useful without requiring a protocol class.
        if self.ollama is not None and hasattr(self.ollama, "model"):
            self.ollama.model = self.selected_model

    # Explicit alias for callers that describe this as a routing selection.
    select_model = set_model

    async def stream_reasoning(self, prompt: str, correlation_id: str | None = None) -> str:
        """Start a streaming reasoning task. Returns the full aggregated text."""
        backend_model = getattr(self.ollama, "backend_model", None)
        if not isinstance(backend_model, str) or not backend_model:
            backend_model = None
        stream_id = await self.aggregator.start_stream(
            self.selected_model,
            correlation_id,
            reason=self.selection_reason,
            backend_model=backend_model,
        )

        task = asyncio.create_task(
            self._stream_task(stream_id, prompt, correlation_id),
            name=f"stream-{stream_id}",
        )
        self._active_tasks[stream_id] = task

        try:
            return await asyncio.wait_for(asyncio.shield(task), timeout=self.timeout_seconds)
        except asyncio.TimeoutError:
            self.logger.warning(
                "llm_stream_timeout",
                extra={"stream_id": stream_id, "timeout_seconds": self.timeout_seconds, "prompt_preview": prompt[:80]},
            )
            if not task.done():
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
            if stream_id in self._active_tasks:
                self._active_tasks.pop(stream_id, None)
            await self.aggregator.handle_timeout(stream_id, "llm_stream_timeout", correlation_id)
            return ""
        except asyncio.CancelledError:
            if stream_id in self._active_tasks:
                self._active_tasks.pop(stream_id, None)
            await self.aggregator.cancel_stream(stream_id, "task_cancelled", correlation_id)
            raise
        finally:
            self._active_tasks.pop(stream_id, None)

    async def generate_buffered(self, prompt: str, max_tokens: int | None = None) -> str:
        """Generate text without publishing chunks before a caller can validate it."""
        generated, metrics = await self.ollama.generate(prompt, max_tokens=max_tokens)
        if not metrics.success or not isinstance(generated, str):
            return ""
        return generated

    async def _stream_task(self, stream_id: str, prompt: str, correlation_id: str | None = None) -> str:
        try:
            async for chunk, done in self.ollama.stream_generate(prompt):
                if chunk:
                    await self.aggregator.add_chunk(stream_id, chunk, correlation_id)
                if done:
                    break
            
            return await self.aggregator.complete_stream(stream_id, correlation_id)
        except Exception as e:
            self.logger.error("stream_task_failed", extra={"stream_id": stream_id, "error": str(e)})
            await self.aggregator.cancel_stream(stream_id, f"error: {str(e)}", correlation_id)
            return ""

    def cancel_all(self) -> None:
        """Cancel all active streaming tasks."""
        for task in self._active_tasks.values():
            task.cancel()
        self._active_tasks.clear()
