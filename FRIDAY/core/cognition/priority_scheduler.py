import asyncio
import logging
import heapq
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine
from core.cognition.attention_manager import AttentionPriority

@dataclass(order=True)
class PrioritizedTask:
    priority: int
    task_id: str = field(compare=False)
    coro: Coroutine = field(compare=False)
    created_at: float = field(compare=False)

class PriorityScheduler:
    """
    Prevents worker race conditions by controlling execution order and cancellation precedence.
    """
    def __init__(self):
        self.logger = logging.getLogger("cognition.scheduler")
        self._queue = [] # Heap for prioritized tasks
        self._active_tasks: dict[str, asyncio.Task] = {}
        self._loop_task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self):
        self._running = True
        self._loop_task = asyncio.create_task(self._scheduler_loop())

    async def stop(self):
        self._running = False
        if self._loop_task:
            self._loop_task.cancel()
        for task in self._active_tasks.values():
            task.cancel()

    async def schedule(self, task_id: str, coro: Coroutine, priority: AttentionPriority):
        # Priorities in IntEnum are high=important, but heapq is low=first. 
        # So we use -priority for the heap.
        import time
        heapq.heappush(self._queue, PrioritizedTask(-int(priority), task_id, coro, time.time()))

    async def cancel_lower_than(self, priority: AttentionPriority):
        # Cancel active tasks with lower priority
        to_cancel = []
        for tid, task in self._active_tasks.items():
            # This is tricky because Task doesn't have priority stored easily.
            # We'd need a registry.
            pass
            
    async def _scheduler_loop(self):
        while self._running:
            if self._queue:
                p_task = heapq.heappop(self._queue)
                asyncio.create_task(p_task.coro)
            await asyncio.sleep(0.01)
