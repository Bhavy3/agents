"""Bounded, relevance-filtered memory context for conversation turns."""

import asyncio
import uuid
from typing import Any

from core.events.event_types import EventType
from core.events.models import Event
from core.memory.memory_index import MemoryIndex
from core.memory.memory_validator import MemoryValidator

MEMORY_QUERY_TIMEOUT_SECONDS = 0.2
MEMORY_CONTEXT_MAX_CHARS = 1200


class MemoryContextMixin:
    """Memory-query handlers; shared turn state remains with the orchestrator."""

    def _init_memory_context(self) -> None:
        self._latest_memory_context = ""
        self._pending_memory_queries: dict[str, asyncio.Future[list[dict[str, Any]]]] = {}
        self._memory_index = MemoryIndex()
        self._memory_validator = MemoryValidator()

    async def _handle_memory_query_result(self, event: Event) -> None:
        future = self._pending_memory_queries.get(event.correlation_id or "")
        if future is not None and not future.done():
            results = event.payload.get("results", [])
            future.set_result(results if isinstance(results, list) else [])

    async def _handle_memory_failure(self, event: Event) -> None:
        if event.payload.get("operation") != "query":
            return
        future = self._pending_memory_queries.get(event.correlation_id or "")
        if future is not None and not future.done():
            future.set_result([])

    async def _request_memory_context(self, query: str) -> str:
        query_id = str(uuid.uuid4())
        future: asyncio.Future[list[dict[str, Any]]] = asyncio.get_running_loop().create_future()
        self._pending_memory_queries[query_id] = future
        try:
            await self.event_bus.publish(Event.create(
                EventType.MEMORY_QUERY_REQUEST,
                {"query": query[:500], "limit": 10},
                self.name,
                query_id,
            ))
            results = await asyncio.wait_for(future, timeout=MEMORY_QUERY_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            self.logger.warning("memory_context_query_timed_out")
            return ""
        except Exception:
            self.logger.exception("memory_context_query_failed")
            return ""
        finally:
            self._pending_memory_queries.pop(query_id, None)
            if not future.done():
                future.cancel()

        lines: list[str] = []
        context_length = 0
        for result in results:
            if not isinstance(result, dict):
                continue
            content = result.get("content", "")
            if not isinstance(content, str):
                continue
            content = " ".join(content.split())
            if (
                not self._memory_validator.validate_content(content).allowed
                or not self._memory_index.text_is_relevant(query, content)
            ):
                continue
            line = f"- {content}"
            added_length = len(line) + (1 if lines else 0)
            if context_length + added_length > MEMORY_CONTEXT_MAX_CHARS:
                continue
            lines.append(line)
            context_length += added_length
        return "\n".join(lines)

    async def _handle_memory_context(self, event: Event) -> None:
        async with self._state_lock:
            context_str = event.payload.get("context", "")
            if len(context_str) > 500:
                context_str = context_str[:497] + "..."
            self._latest_memory_context = context_str
