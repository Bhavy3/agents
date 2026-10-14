import asyncio
import json
import os
import re
import sqlite3

from core.memory.memory_models import MemoryRecord, MemoryType
from core.memory.memory_validator import MemoryValidator


class MemoryStore:
    def __init__(self, db_path: str = "data/memory/friday_memory.db"):
        self.db_path = db_path
        self._shared_conn = sqlite3.connect(self.db_path, check_same_thread=False) if self.db_path == ":memory:" else None
        self.validator = MemoryValidator()
        self._ensure_dir()
        self._init_db()

    def _ensure_dir(self):
        if self.db_path != ":memory:":
            dir_path = os.path.dirname(self.db_path)
            if dir_path:
                os.makedirs(dir_path, exist_ok=True)

    def _get_connection(self):
        if self._shared_conn is not None:
            return self._shared_conn
        return sqlite3.connect(self.db_path)

    def _init_db(self):
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    source TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    explicit_user_approved INTEGER NOT NULL,
                    metadata_json TEXT NOT NULL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_type ON memories(type)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_created ON memories(created_at)")

    async def save(self, record: MemoryRecord, allow_update: bool = False) -> None:
        await asyncio.to_thread(self._save_sync, record, allow_update)

    def _save_sync(self, record: MemoryRecord, allow_update: bool = False) -> None:
        validation = self.validator.validate(record)
        if not validation.allowed:
            raise ValueError(f"Memory record rejected: {validation.reason}")
        with self._get_connection() as conn:
            values = (
                record.id,
                record.type.value,
                record.content,
                record.created_at,
                record.updated_at,
                record.source,
                record.confidence,
                1 if record.explicit_user_approved else 0,
                json.dumps(record.metadata)
            )
            if allow_update:
                conn.execute("""
                    INSERT INTO memories
                    (id, type, content, created_at, updated_at, source, confidence, explicit_user_approved, metadata_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        type = excluded.type,
                        content = excluded.content,
                        created_at = excluded.created_at,
                        updated_at = excluded.updated_at,
                        source = excluded.source,
                        confidence = excluded.confidence,
                        explicit_user_approved = excluded.explicit_user_approved,
                        metadata_json = excluded.metadata_json
                """, values)
            else:
                conn.execute("""
                    INSERT INTO memories
                    (id, type, content, created_at, updated_at, source, confidence, explicit_user_approved, metadata_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, values)

    async def query(self, memory_type: MemoryType | None = None, limit: int = 100) -> list[MemoryRecord]:
        return await asyncio.to_thread(self._query_sync, memory_type, limit)

    def _query_sync(self, memory_type: MemoryType | None = None, limit: int = 100) -> list[MemoryRecord]:
        query = "SELECT * FROM memories"
        params = []
        if memory_type:
            query += " WHERE type = ?"
            params.append(memory_type.value)
        
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
            
        with self._get_connection() as conn:
            cursor = conn.execute(query, params)
            return [self._row_to_record(row) for row in cursor.fetchall()]

    async def search_by_text(self, text: str, limit: int = 10) -> list[MemoryRecord]:
        return await asyncio.to_thread(self._search_sync, text, limit)

    def _search_sync(self, text: str, limit: int = 10) -> list[MemoryRecord]:
        terms = list(dict.fromkeys(re.findall(r"[\w'-]+", text.lower())))[:20]
        if not terms:
            return self._query_sync(limit=limit)
        clauses = " OR ".join("content LIKE ?" for _ in terms)
        query = f"SELECT * FROM memories WHERE {clauses} ORDER BY created_at DESC LIMIT ?"
        params = [f"%{term}%" for term in terms]
        params.append(max(1, min(limit, 500)))

        with self._get_connection() as conn:
            cursor = conn.execute(query, params)
            return [self._row_to_record(row) for row in cursor.fetchall()]

    def _row_to_record(self, row: tuple) -> MemoryRecord:
        return MemoryRecord(
            id=row[0],
            type=MemoryType(row[1]),
            content=row[2],
            created_at=row[3],
            updated_at=row[4],
            source=row[5],
            confidence=row[6],
            explicit_user_approved=bool(row[7]),
            metadata=json.loads(row[8])
        )

    async def delete(self, record_id: str) -> None:
        await asyncio.to_thread(self._delete_sync, record_id)

    def _delete_sync(self, record_id: str) -> None:
        with self._get_connection() as conn:
            conn.execute("DELETE FROM memories WHERE id = ?", (record_id,))
