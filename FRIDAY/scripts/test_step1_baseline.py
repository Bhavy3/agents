import asyncio
import sys
import time
from pathlib import Path

root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))

from core.events.bus import EventBus
from core.config.settings import load_settings
from core.llm.local_llm_client import create_llm_client

sys.stdout.reconfigure(encoding="utf-8")

async def baseline():
    s = load_settings()
    bus = EventBus()
    await bus.start()
    client = create_llm_client(s.ollama_base_url, s.ollama_model, 30.0, 2, s.llm_provider)

    # Baseline query
    start = time.perf_counter()
    response, metrics = await client.generate("hello", max_tokens=5)
    elapsed = time.perf_counter() - start

    cleaned = response.strip() if response else ""
    is_active = (not client._client.is_closed) if client._client else True
    print(f"Pre-idle baseline: {elapsed:.2f}s response | response='{cleaned}'")
    print(f"Client state: active={is_active}")
    print(f"Bus state: started={bus._running}")

    await client.aclose()
    await bus.stop()

if __name__ == "__main__":
    asyncio.run(baseline())
