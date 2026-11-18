import asyncio

import pytest

from core.events.bus import EventBus
from core.events.event_types import EventType
from core.events.models import Event
from core.workers.mail_watcher import MailWatcherWorker

MSG_1 = ("101", "Alice <alice@example.com>", "Project update", "The build is green.")
MSG_2 = ("102", "Bob <bob@example.com>", "Invoice", "Invoice #42 attached.")


async def _collect_worker_events(worker: MailWatcherWorker, polls: list, max_seconds: float = 3.0):
    bus = EventBus()
    await bus.start()
    received: list[Event] = []
    bus.subscribe(EventType.NEW_EMAIL, received.append)
    worker.event_bus = bus

    async def run_until_polled():
        while len(polls) < 1 and not worker._first_poll_done:
            await asyncio.sleep(0.05)

    task = asyncio.create_task(worker.work())
    try:
        await asyncio.wait_for(run_until_polled(), timeout=max_seconds)
    except asyncio.TimeoutError:
        pass
    finally:
        worker._stop_event.set()
        await task
        await bus.drain()
        await bus.stop()
    return received


@pytest.mark.asyncio
async def test_first_poll_is_silent():
    polls = [MSG_1]

    def fake_fetch():
        return polls

    worker = MailWatcherWorker(EventBus(), user="u", password="p", poll_interval_seconds=0.1)
    worker._fetch_unread_sync = fake_fetch
    received = await _collect_worker_events(worker, polls)

    assert received == []  # existing mail is marked seen, not announced


@pytest.mark.asyncio
async def test_new_mail_after_startup_is_announced():
    polls = [MSG_1]

    def fake_fetch():
        return list(polls)

    worker = MailWatcherWorker(EventBus(), user="u", password="p", poll_interval_seconds=0.1)
    worker._fetch_unread_sync = fake_fetch

    bus = EventBus()
    await bus.start()
    received: list[Event] = []
    bus.subscribe(EventType.NEW_EMAIL, received.append)
    worker.event_bus = bus

    task = asyncio.create_task(worker.work())
    # First poll silent
    for _ in range(100):
        if worker._first_poll_done:
            break
        await asyncio.sleep(0.02)
    # New mail arrives
    polls.append(MSG_2)
    for _ in range(100):
        if received:
            break
        await asyncio.sleep(0.02)

    worker._stop_event.set()
    await task
    await bus.drain()
    await bus.stop()

    assert len(received) == 1
    assert received[0].payload["subject"] == "Invoice"
    assert received[0].payload["sender"] == "Bob <bob@example.com>"
    assert received[0].payload["snippet"] == "Invoice #42 attached."


@pytest.mark.asyncio
async def test_same_uid_announced_once():
    polls = [MSG_1]

    def fake_fetch():
        return [MSG_1]

    worker = MailWatcherWorker(EventBus(), user="u", password="p", poll_interval_seconds=0.1)
    worker._fetch_unread_sync = fake_fetch
    # Pretend startup already happened so MSG_1 would be announced if not deduped
    worker._first_poll_done = True

    bus = EventBus()
    await bus.start()
    received: list[Event] = []
    bus.subscribe(EventType.NEW_EMAIL, received.append)
    worker.event_bus = bus

    task = asyncio.create_task(worker.work())
    await asyncio.sleep(0.4)  # several poll cycles
    worker._stop_event.set()
    await task
    await bus.drain()
    await bus.stop()

    assert len(received) == 1  # dedup across polls


@pytest.mark.asyncio
async def test_poll_failure_does_not_crash_loop():
    call_count = {"n": 0}

    def flaky_fetch():
        call_count["n"] += 1
        if call_count["n"] % 2 == 1:
            raise ConnectionError("imap down")
        return [MSG_2]

    worker = MailWatcherWorker(EventBus(), user="u", password="p", poll_interval_seconds=0.05)
    worker._fetch_unread_sync = flaky_fetch
    worker._first_poll_done = True

    bus = EventBus()
    await bus.start()
    received: list[Event] = []
    bus.subscribe(EventType.NEW_EMAIL, received.append)
    worker.event_bus = bus

    task = asyncio.create_task(worker.work())
    await asyncio.sleep(0.4)
    worker._stop_event.set()
    await task
    await bus.drain()
    await bus.stop()

    assert call_count["n"] >= 3  # loop kept running through failures
    assert len(received) == 1


@pytest.mark.asyncio
async def test_missing_credentials_stops_immediately():
    worker = MailWatcherWorker(EventBus(), user="", password="")
    # Must return promptly without polling
    await asyncio.wait_for(worker.work(), timeout=1.0)


def test_new_email_contract_registered():
    from core.events.contracts import EVENT_CONTRACTS

    schema = EVENT_CONTRACTS.get(EventType.NEW_EMAIL)
    assert schema == {"subject": str, "sender": str, "snippet": str}
