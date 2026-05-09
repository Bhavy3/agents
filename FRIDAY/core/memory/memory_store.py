import sqlite3
import json
import os
import asyncio
from typing import Any
from core.memory.memory_models import MemoryRecord, MemoryType


class MemoryStore:
    def __init__(self, db_path: str = "data/memory/friday_memory.db"):
        self.db_path = db_path
        self._ensure_dir()
        self._init_db()

    def _ensure_dir(self):
        if self.db_path != ":memory:":
            dir_path = os.path.dirname(self.db_path)
            if dir_path:
                os.makedirs(dir_path, exist_ok=True)

    def _get_connection(self):
        return sqlite3.connect(self.db_path)

    def _init_db(self):
        try:
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
        except sqlite3.Error as e:
            # Handle potential corruption by logging (in a real app, might try recovery)
            print(f"MemoryStore init error: {e}")

    async def save(self, record: MemoryRecord) -> None:
        await asyncio.to_thread(self._save_sync, record)

    def _save_sync(self, record: MemoryRecord) -> None:
        with self._get_connection() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO memories 
                (id, type, content, created_at, updated_at, source, confidence, explicit_user_approved, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                record.id,
                record.type.value,
                record.content,
                record.created_at,
                record.updated_at,
                record.source,
                record.confidence,
                1 if record.explicit_user_approved else 0,
                json.dumps(record.metadata)
            ))

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
        # Simple LIKE search for deterministic recall as requested (no vector DB)
        query = "SELECT * FROM memories WHERE content LIKE ? ORDER BY created_at DESC LIMIT ?"
        params = [f"%{text}%", limit]
            
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
