import asyncio
import pytest
from core.events.bus import EventBus
from core.workers.supervisor import WorkerSupervisor
from core.workers.base_worker import BaseWorker

class SlowCrashWorker(BaseWorker):
    def __init__(self, bus: EventBus):
        super().__init__("slow_crash_worker", bus)

    async def work(self) -> None:
        raise RuntimeError("slow crash test")

@pytest.mark.asyncio
async def test_supervisor_quarantines_slow_crashes():
    bus = EventBus(max_queue_size=1000)
    await bus.start()
    
    worker = SlowCrashWorker(bus)
    supervisor = WorkerSupervisor(
        bus, 
        workers=[worker],
        metrics=None,
        max_restarts_per_minute=20,
        max_total_restarts=3,
        max_total_restarts_window_seconds=10.0
    )
    
    await supervisor.start()
    
    try:
        # Wait for quarantine to trigger (max 3 restarts)
        # Delay sequence: 1, 2, 4 seconds = 7 seconds approx
        await asyncio.sleep(8.0)
        
        # Worker should be quarantined
        health_state = worker.health.state.value
        assert health_state == "quarantined", f"Expected quarantined, got {health_state}"
    finally:
        await supervisor.stop()
        await bus.drain()
        await bus.stop()
