"""Async helpers shared across FRIDAY workers.

The event loop keeps only a weak reference to tasks. A task created and not
assigned anywhere can therefore be collected before it runs, which drops real
work silently. `spawn_background` keeps a strong reference until completion.
"""

import asyncio

_BACKGROUND_TASKS: set[asyncio.Task] = set()


def spawn_background(coro) -> asyncio.Task:
    """Schedule `coro` and keep it alive until it finishes."""
    task = asyncio.create_task(coro)
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)
    return task


def pending_background_tasks() -> int:
    """Number of fire-and-forget tasks still running (for tests and metrics)."""
    return len(_BACKGROUND_TASKS)
