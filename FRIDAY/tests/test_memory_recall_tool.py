import time
import pytest
from core.memory.memory_models import MemoryRecord, MemoryType
from core.tools.tool_registry import ToolRegistry

@pytest.mark.asyncio
async def test_memory_recall_tool_fts5_integration(tmp_path):
    db_file = str(tmp_path / "test_recall.db")
    registry = ToolRegistry()
    from core.memory.memory_store import MemoryStore
    store = MemoryStore(db_file)
    registry._memory_store = store

    now = time.time()
    await store.save(MemoryRecord(
        id="mem_1",
        type=MemoryType.APPROVED_FACT,
        content="n8n is running locally on port 5678 and requires X-N8N-API-KEY header",
        created_at=now,
        updated_at=now,
        source="learning",
        confidence=1.0,
        explicit_user_approved=True,
        metadata={}
    ))
    await store.save(MemoryRecord(
        id="mem_2",
        type=MemoryType.PREFERENCE,
        content="User prefers python scripts with pyproject.toml",
        created_at=now,
        updated_at=now,
        source="conversation",
        confidence=1.0,
        explicit_user_approved=True,
        metadata={}
    ))

    recall_fn = registry.get_tool("memory_recall")
    assert recall_fn is not None

    res = await recall_fn(query="n8n port")
    assert res.success is True
    assert "5678" in res.output
    assert res.metadata["count"] >= 1

    res_pref = await recall_fn(query="pyproject")
    assert res_pref.success is True
    assert "python" in res_pref.output

    res_empty = await recall_fn(query="quantum teleportation")
    assert res_empty.success is True
    assert res_empty.metadata["count"] == 0
