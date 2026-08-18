import asyncio
import time
import sys
import os

# Add FRIDAY dir to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.memory.memory_store import MemoryStore
from core.memory.memory_models import MemoryRecord, MemoryType

async def main():
    store = MemoryStore("data/memory/friday_memory.db")
    record = MemoryRecord(
        id=f"mem_pinned_test",
        type=MemoryType.PINNED_NOTE,
        content="The user's secret code name is 'NIGHTHAWK'. Please use it.",
        created_at=time.time(),
        updated_at=time.time(),
        source="system_test",
        confidence=1.0,
        explicit_user_approved=True,
        metadata={}
    )
    await store.save(record)
    print("Successfully injected test memory record.")

if __name__ == "__main__":
    asyncio.run(main())
