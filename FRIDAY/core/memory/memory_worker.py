import asyncio
import time
import logging
from typing import Any
from core.workers.base_worker import BaseWorker
from core.events.bus import EventBus
from core.events.event_types import EventType
from core.events.models import Event
from core.memory.memory_models import MemoryRecord, MemoryType
from core.memory.memory_store import MemoryStore
from core.memory.memory_validator import MemoryValidator
from core.memory.memory_index import MemoryIndex


class MemoryWorker(BaseWorker):
    def __init__(self, event_bus: EventBus, metrics: Any = None, db_path: str = "data/memory/friday_memory.db"):
        super().__init__("memory_worker", event_bus)
        self.store = MemoryStore(db_path)
        self.validator = MemoryValidator()
        self.index = MemoryIndex()
        self.metrics = metrics

        # Local stats (fallback if global metrics not provided)
        self._memories_stored = 0
        self._recall_queries = 0
        self._denied_writes = 0
        self._degraded_mode = False

    async def run(self) -> None:
        self.event_bus.subscribe(EventType.MEMORY_WRITE_REQUEST, self.handle_write_request)
        self.event_bus.subscribe(EventType.MEMORY_QUERY_REQUEST, self.handle_query_request)
        await super().run()

    async def work(self) -> None:
        context_refresh_timer = 0
        while not self.should_stop:
            self.heartbeat(f"memory [stored={self._memories_stored} queries={self._recall_queries} denied={self._denied_writes}]")
            
            # Periodic context refresh (every 30s)
            context_refresh_timer += 1
            if context_refresh_timer >= 30:
                await self._refresh_context()
                context_refresh_timer = 0
                
            await asyncio.sleep(1.0)

    async def _refresh_context(self) -> None:
        try:
            # Fetch pinned notes and preferences
            pinned = await self.store.query(MemoryType.PINNED_NOTE, limit=5)
            prefs = await self.store.query(MemoryType.PREFERENCE, limit=10)
            
            context_parts = []
            if pinned:
                context_parts.append("PINNED NOTES:")
                for p in pinned:
                    context_parts.append(f"- {p.content}")
            
            if prefs:
                context_parts.append("\nUSER PREFERENCES:")
                for p in prefs:
                    context_parts.append(f"- {p.content}")
            
            if context_parts:
                full_context = "\n".join(context_parts)
                await self.event_bus.publish(Event.create(
                    EventType.MEMORY_CONTEXT_READY,
                    {"context": full_context},
                    self.name
                ))
        except Exception:
            self.logger.exception("context_refresh_failed")

    async def handle_write_request(self, event: Event) -> None:
        payload = event.payload
        try:
            memory_type_str = payload.get("type", "preference")
            record = MemoryRecord(
                id=payload.get("id", f"mem_{int(time.time() * 1000)}"),
                type=MemoryType(memory_type_str),
                content=payload["content"],
                created_at=payload.get("created_at", time.time()),
                updated_at=time.time(),
                source=payload.get("source", "unknown"),
                confidence=payload.get("confidence", 1.0),
                explicit_user_approved=payload.get("explicit_user_approved", False),
                metadata=payload.get("metadata", {})
            )

            validation = self.validator.validate(record)
            if not validation.allowed:
                self._denied_writes += 1
                if self.metrics:
                    self.metrics.denied_memory_writes += 1
                await self.event_bus.publish(Event.create(
                    EventType.MEMORY_DENIED,
                    {"id": record.id, "reason": validation.reason},
                    self.name,
                    event.correlation_id
                ))
                return

            start_time = time.time()
            await self.store.save(record)
            latency = (time.time() - start_time) * 1000

            self._memories_stored += 1
            if self.metrics:
                self.metrics.memories_stored += 1
                self.metrics.memory_db_latency_ms = latency
            await self.event_bus.publish(Event.create(
                EventType.MEMORY_WRITE_COMPLETED,
                {"id": record.id, "latency_ms": latency},
                self.name,
                event.correlation_id
            ))

        except Exception as e:
            self.logger.exception("memory_write_failed")
            await self.event_bus.publish(Event.create(
                EventType.MEMORY_FAILURE,
                {"operation": "write", "error": str(e)},
                self.name,
                event.correlation_id
            ))

    async def handle_query_request(self, event: Event) -> None:
        payload = event.payload
        try:
            query_text = payload.get("query", "")
            memory_type_str = payload.get("type")
            memory_type = MemoryType(memory_type_str) if memory_type_str else None

            self._recall_queries += 1
            if self.metrics:
                self.metrics.recall_queries += 1
                
            start_time = time.time()

            # 1. Fetch from store
            if query_text:
                records = await self.store.search_by_text(query_text)
                # Filter by type if requested
                if memory_type:
                    records = [r for r in records if r.type == memory_type]
            else:
                records = await self.store.query(memory_type)

            # 2. Rank deterministically
            ranked = self.index.rank(query_text, records)
            latency = (time.time() - start_time) * 1000
            if self.metrics:
                self.metrics.memory_db_latency_ms = latency

            # 3. Format result
            results = [{
                "id": r.id,
                "type": r.type.value,
                "content": r.content,
                "confidence": r.confidence,
                "metadata": r.metadata
            } for r in ranked]

            await self.event_bus.publish(Event.create(
                EventType.MEMORY_QUERY_RESULT,
                {"results": results, "latency_ms": latency},
                self.name,
                event.correlation_id
            ))

        except Exception as e:
            self.logger.exception("memory_query_failed")
            await self.event_bus.publish(Event.create(
                EventType.MEMORY_FAILURE,
                {"operation": "query", "error": str(e)},
                self.name,
                event.correlation_id
            ))
