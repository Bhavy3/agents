"""Fire-and-forget tasks must stay referenced until they finish."""

import asyncio

import pytest

from core.asyncio_utils import pending_background_tasks, spawn_background


@pytest.mark.asyncio
async def test_spawn_background_keeps_the_task_alive_until_done():
    completed = asyncio.Event()

    async def work():
        await asyncio.sleep(0)
        completed.set()

    task = spawn_background(work())

    assert not task.done()
    await task
    assert completed.is_set()
    assert task.cancelled() is False


@pytest.mark.asyncio
async def test_pending_count_returns_to_zero(monkeypatch):
    baseline = pending_background_tasks()

    async def work():
        await asyncio.sleep(0)

    task = spawn_background(work())
    assert pending_background_tasks() >= baseline
    await task
    await asyncio.sleep(0)

    assert pending_background_tasks() == baseline
