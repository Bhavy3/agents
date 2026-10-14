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

    async def stream_reasoning(self, prompt: str, correlation_id: str | None = None) -> str:
        """Start a streaming reasoning task. Returns the full aggregated text."""
        stream_id = await self.aggregator.start_stream(self.ollama.model, correlation_id)

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