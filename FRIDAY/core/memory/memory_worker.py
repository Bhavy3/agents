import asyncio
import re
import time
import uuid
from typing import Any

from core.workers.base_worker import BaseWorker
from core.events.bus import EventBus
from core.events.event_types import EventType
from core.events.models import Event
from core.memory.memory_models import MemoryRecord, MemoryType
from core.memory.memory_store import MemoryStore
from core.memory.memory_validator import MemoryValidator
from core.memory.memory_index import MemoryIndex


def compress_memory_content(content: str) -> str:
    normalized = " ".join(content.split())
    sentences = re.split(r"(?<=[.!?])\s+", normalized)
    unique_sentences: list[str] = []
    seen: set[str] = set()
    for sentence in sentences:
        key = sentence.casefold()
        if key and key not in seen:
            unique_sentences.append(sentence)
            seen.add(key)
    return " ".join(unique_sentences)


def summarize_memory_content(content: str, max_length: int = 1200) -> str:
    compressed = compress_memory_content(content)
    if len(compressed) <= max_length:
        return compressed

    sentences = re.split(r"(?<=[.!?])\s+", compressed)
    important = re.compile(
        r"\b(name|prefer|preference|like|likes|goal|want|need|must|always|never|cannot|can't|constraint|important|keep|preserve|avoid|requires)\b",
        re.IGNORECASE,
    )

    def has_name(sentence: str) -> bool:
        first_word = sentence.split(maxsplit=1)[0].strip(".,!?;:")
        common_openers = {"a", "an", "i", "my", "the", "this", "user", "we"}
        candidate_text = sentence
        if first_word.casefold() in common_openers:
            candidate_text = sentence[len(first_word):]
        return bool(re.search(r"\b[A-Z][a-z]{2,}\b", candidate_text))

    ranked = sorted(
        enumerate(sentences),
        key=lambda item: (bool(important.search(item[1])), has_name(item[1]), -item[0]),
        reverse=True,
    )
    selected: set[int] = set()
    used_length = 0
    for index, sentence in ranked:
        added_length = len(sentence) + (1 if selected else 0)
        if sentence and used_length + added_length <= max_length:
            selected.add(index)
            used_length += added_length
    return " ".join(sentence for index, sentence in enumerate(sentences) if index in selected)


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
        context_refresh_timer = 30 # Fire immediately on startup
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
            pinned = [
                record for record in await self.store.query(MemoryType.PINNED_NOTE, limit=5)
                if self.validator.validate(record).allowed
            ]
            prefs = [
                record for record in await self.store.query(MemoryType.PREFERENCE, limit=10)
                if self.validator.validate(record).allowed
            ]
            
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

    async def _deny_write(self, record_id: str, reason: str | None, correlation_id: str | None) -> None:
        self._denied_writes += 1
        if self.metrics:
            self.metrics.denied_memory_writes += 1
        await self.event_bus.publish(Event.create(
            EventType.MEMORY_DENIED,
            {"id": record_id, "reason": reason or "memory_validation_failed"},
            self.name,
            correlation_id,
        ))

    async def handle_write_request(self, event: Event) -> None:
        payload = event.payload
        try:
            raw_content = payload.get("content")
            if not isinstance(raw_content, str) or len(raw_content) > self.validator.max_content_length:
                record_id = str(payload.get("id") or f"mem_{uuid.uuid4().hex}")
                length = len(raw_content) if isinstance(raw_content, str) else 0
                await self._deny_write(
                    record_id,
                    f"content_length_violation: {length}",
                    event.correlation_id,
                )
                return

            record_id = str(payload.get("id") or f"mem_{uuid.uuid4().hex}")
            raw_validation = self.validator.validate_content(raw_content)
            if not raw_validation.allowed:
                await self._deny_write(record_id, raw_validation.reason, event.correlation_id)
                return

            memory_type_str = payload.get("type", "preference")
            memory_type = MemoryType(memory_type_str)
            content = (
                summarize_memory_content(raw_content)
                if memory_type == MemoryType.CONVERSATION_SUMMARY
                else compress_memory_content(raw_content)
            )
            record = MemoryRecord(
                id=record_id,
                type=memory_type,
                content=content,
                created_at=payload.get("created_at", time.time()),
                updated_at=time.time(),
                source=payload.get("source", "unknown"),
                confidence=payload.get("confidence", 1.0),
                explicit_user_approved=payload.get("explicit_user_approved", False),
                metadata=payload.get("metadata", {})
            )

            validation = self.validator.validate(record)
            if not validation.allowed:
                await self._deny_write(record.id, validation.reason, event.correlation_id)
                return

            start_time = time.time()
            await self.store.save(record, allow_update=bool(payload.get("id")))
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
            query_text = str(payload.get("query", ""))[:500]
            memory_type_str = payload.get("type")
            memory_type = MemoryType(memory_type_str) if memory_type_str else None
            result_limit = max(1, min(int(payload.get("limit", 10)), 10))

            self._recall_queries += 1
            if self.metrics:
                self.metrics.recall_queries += 1
                
            start_time = time.time()

            # 1. Fetch from store
            if query_text:
                records = await self.store.search_by_text(query_text, limit=200)
                # Filter by type if requested
                if memory_type:
                    records = [r for r in records if r.type == memory_type]
            else:
                records = await self.store.query(memory_type, limit=200)

            # 2. Rank deterministically
            records = [record for record in records if self.validator.validate(record).allowed]
            ranked = self.index.rank(query_text, records)
            if query_text:
                ranked = [record for record in ranked if self.index.is_relevant(query_text, record)]
            ranked = ranked[:result_limit]
            latency = (time.time() - start_time) * 1000
            if self.metrics:
                self.metrics.memory_db_latency_ms = latency

            # 3. Format result
            results = [{
                "type": r.type.value,
                "content": r.content,
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
