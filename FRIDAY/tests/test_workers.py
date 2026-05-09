import asyncio
import unittest

from core.events.bus import EventBus
from core.events.event_types import EventType
from core.events.models import Event
from core.workers.base_worker import BaseWorker
from core.workers.health import WorkerHealth
import core.workers.supervisor as supervisor_module
from core.workers.supervisor import WorkerSupervisor


class FailingWorker(BaseWorker):
    def __init__(self, event_bus: EventBus) -> None:
        super().__init__("failing_worker", event_bus)
        self.runs = 0

    async def work(self) -> None:
        self.runs += 1
        if self.runs == 1:
            raise RuntimeError("intentional test failure")
        while not self.should_stop:
            await asyncio.sleep(0.01)


class WorkerTests(unittest.TestCase):
    def test_supervisor_restarts_failed_worker(self) -> None:
        async def scenario() -> bool:
            bus = EventBus()
            worker = FailingWorker(bus)
            supervisor = WorkerSupervisor(bus, [worker])
            restarts: list[Event] = []

            async def handle_restart(event: Event) -> None:
                restarts.append(event)

            bus.subscribe(EventType.WORKER_RESTARTED, handle_restart)
            await bus.start()
            await supervisor.start()
            await asyncio.sleep(1.2)
            await supervisor.stop()
            await bus.drain()
            await bus.stop()
            return worker.runs >= 2 and bool(restarts) and worker.health.restart_count >= 1

        self.assertTrue(asyncio.run(scenario()))

    def test_supervisor_survives_restart_loop(self) -> None:
        class AlwaysFailingWorker(BaseWorker):
            async def work(self) -> None:
                raise RuntimeError("restart loop test")

        async def scenario() -> int:
            original_delay = supervisor_module.DEFAULT_WORKER_RESTART_DELAY_SECONDS
            original_max_delay = supervisor_module.MAX_WORKER_RESTART_DELAY_SECONDS
            supervisor_module.DEFAULT_WORKER_RESTART_DELAY_SECONDS = 0.01
            supervisor_module.MAX_WORKER_RESTART_DELAY_SECONDS = 0.02
            try:
                bus = EventBus()
                worker = AlwaysFailingWorker("always_failing", bus)
                supervisor = WorkerSupervisor(bus, [worker])
                await bus.start()
                await supervisor.start()
                await asyncio.sleep(0.08)
                await supervisor.stop()
                await bus.drain()
                await bus.stop()
                return worker.health.restart_count
            finally:
                supervisor_module.DEFAULT_WORKER_RESTART_DELAY_SECONDS = original_delay
                supervisor_module.MAX_WORKER_RESTART_DELAY_SECONDS = original_max_delay

        self.assertGreaterEqual(asyncio.run(scenario()), 2)

    def test_supervisor_quarantines_restart_loop(self) -> None:
        class AlwaysFailingWorker(BaseWorker):
            async def work(self) -> None:
                raise RuntimeError("too many restarts")

        async def scenario() -> tuple[str, int]:
            original_delay = supervisor_module.DEFAULT_WORKER_RESTART_DELAY_SECONDS
            supervisor_module.DEFAULT_WORKER_RESTART_DELAY_SECONDS = 0.01
            try:
                bus = EventBus()
                worker = AlwaysFailingWorker("looping_worker", bus)
                supervisor = WorkerSupervisor(bus, [worker], max_restarts_per_minute=1)
                await bus.start()
                await supervisor.start()
                await asyncio.sleep(0.08)
                await supervisor.stop()
                await bus.drain()
                await bus.stop()
                return worker.health.state.value, worker.health.restart_count
            finally:
                supervisor_module.DEFAULT_WORKER_RESTART_DELAY_SECONDS = original_delay

        state, restart_count = asyncio.run(scenario())
        self.assertEqual(state, "quarantined")
        self.assertEqual(restart_count, 2)

    def test_critical_failure_event_emitted_on_quarantine(self) -> None:
        class AlwaysFailingWorker(BaseWorker):
            async def work(self) -> None:
                raise RuntimeError("quarantine me")

        async def scenario() -> tuple[str, int]:
            original_delay = supervisor_module.DEFAULT_WORKER_RESTART_DELAY_SECONDS
            supervisor_module.DEFAULT_WORKER_RESTART_DELAY_SECONDS = 0.01
            try:
                bus = EventBus()
                worker = AlwaysFailingWorker("critical_looping_worker", bus)
                supervisor = WorkerSupervisor(bus, [worker], max_restarts_per_minute=1)
                critical_events: list[Event] = []

                async def handle_critical(event: Event) -> None:
                    critical_events.append(event)

                bus.subscribe(EventType.CRITICAL_WORKER_FAILURE, handle_critical)
                await bus.start()
                await supervisor.start()
                await asyncio.sleep(0.08)
                await supervisor.stop()
                await bus.drain()
                await bus.stop()
                return worker.health.state.value, len(critical_events)
            finally:
                supervisor_module.DEFAULT_WORKER_RESTART_DELAY_SECONDS = original_delay

        state, critical_count = asyncio.run(scenario())
        self.assertEqual(state, "quarantined")
        self.assertEqual(critical_count, 1)

    def test_disabled_state_is_explicit(self) -> None:
        health = WorkerHealth("manual_disabled")
        health.mark_disabled()
        self.assertEqual(health.state.value, "disabled")
        self.assertFalse(health.alive)

    def test_failed_transitions_to_restarting_before_relaunch(self) -> None:
        class AlwaysFailingWorker(BaseWorker):
            async def work(self) -> None:
                raise RuntimeError("observe restarting")

        async def scenario() -> tuple[str, int]:
            original_delay = supervisor_module.DEFAULT_WORKER_RESTART_DELAY_SECONDS
            supervisor_module.DEFAULT_WORKER_RESTART_DELAY_SECONDS = 0.2
            try:
                bus = EventBus()
                worker = AlwaysFailingWorker("restart_observed_worker", bus)
                supervisor = WorkerSupervisor(bus, [worker], max_restarts_per_minute=5)
                await bus.start()
                await supervisor.start()
                await asyncio.sleep(0.05)
                state = worker.health.state.value
                restart_count = worker.health.restart_count
                await supervisor.stop()
                await bus.drain()
                await bus.stop()
                return state, restart_count
            finally:
                supervisor_module.DEFAULT_WORKER_RESTART_DELAY_SECONDS = original_delay

        state, restart_count = asyncio.run(scenario())
        self.assertEqual(state, "restarting")
        self.assertEqual(restart_count, 1)

    def test_restarted_worker_reaches_running_with_fresh_task_generation(self) -> None:
        async def scenario() -> tuple[str, int, int]:
            original_delay = supervisor_module.DEFAULT_WORKER_RESTART_DELAY_SECONDS
            supervisor_module.DEFAULT_WORKER_RESTART_DELAY_SECONDS = 0.01
            try:
                bus = EventBus()
                worker = FailingWorker(bus)
                supervisor = WorkerSupervisor(bus, [worker], max_restarts_per_minute=5)
                await bus.start()
                await supervisor.start()
                await asyncio.sleep(0.08)
                state = worker.health.state.value
                restart_count = worker.health.restart_count
                generation = supervisor.current_worker_task_generation(worker.name)
                await supervisor.stop()
                await bus.drain()
                await bus.stop()
                return state, restart_count, generation
            finally:
                supervisor_module.DEFAULT_WORKER_RESTART_DELAY_SECONDS = original_delay

        state, restart_count, generation = asyncio.run(scenario())
        self.assertEqual(state, "running")
        self.assertEqual(restart_count, 1)
        self.assertGreaterEqual(generation, 2)

    def test_failed_does_not_persist_when_restart_is_scheduled(self) -> None:
        class AlwaysFailingWorker(BaseWorker):
            async def work(self) -> None:
                raise RuntimeError("failed should not stick")

        async def scenario() -> str:
            original_delay = supervisor_module.DEFAULT_WORKER_RESTART_DELAY_SECONDS
            supervisor_module.DEFAULT_WORKER_RESTART_DELAY_SECONDS = 0.2
            try:
                bus = EventBus()
                worker = AlwaysFailingWorker("failed_not_terminal_worker", bus)
                supervisor = WorkerSupervisor(bus, [worker], max_restarts_per_minute=5)
                await bus.start()
                await supervisor.start()
                await asyncio.sleep(0.05)
                state = worker.health.state.value
                await supervisor.stop()
                await bus.drain()
                await bus.stop()
                return state
            finally:
                supervisor_module.DEFAULT_WORKER_RESTART_DELAY_SECONDS = original_delay

        self.assertNotEqual(asyncio.run(scenario()), "failed")

    def test_supervisor_coroutine_remains_alive_after_failure(self) -> None:
        class AlwaysFailingWorker(BaseWorker):
            async def work(self) -> None:
                raise RuntimeError("supervisor should continue")

        async def scenario() -> tuple[bool, str]:
            original_delay = supervisor_module.DEFAULT_WORKER_RESTART_DELAY_SECONDS
            supervisor_module.DEFAULT_WORKER_RESTART_DELAY_SECONDS = 0.2
            try:
                bus = EventBus()
                worker = AlwaysFailingWorker("loop_lifetime_worker", bus)
                supervisor = WorkerSupervisor(bus, [worker], max_restarts_per_minute=5)
                await bus.start()
                await supervisor.start()
                await asyncio.sleep(0.05)
                alive = supervisor.is_supervising(worker.name)
                state = worker.health.state.value
                await supervisor.stop()
                await bus.drain()
                await bus.stop()
                return alive, state
            finally:
                supervisor_module.DEFAULT_WORKER_RESTART_DELAY_SECONDS = original_delay

        alive, state = asyncio.run(scenario())
        self.assertTrue(alive)
        self.assertEqual(state, "restarting")

    def test_restart_loop_counter_increments_until_quarantine(self) -> None:
        class AlwaysFailingWorker(BaseWorker):
            async def work(self) -> None:
                raise RuntimeError("count me")

        async def scenario() -> tuple[str, int, int]:
            original_delay = supervisor_module.DEFAULT_WORKER_RESTART_DELAY_SECONDS
            supervisor_module.DEFAULT_WORKER_RESTART_DELAY_SECONDS = 0.01
            try:
                bus = EventBus()
                worker = AlwaysFailingWorker("counter_quarantine_worker", bus)
                supervisor = WorkerSupervisor(bus, [worker], max_restarts_per_minute=2)
                await bus.start()
                await supervisor.start()
                await asyncio.sleep(0.08)
                state = worker.health.state.value
                restart_count = worker.health.restart_count
                generation = supervisor.current_worker_task_generation(worker.name)
                await supervisor.stop()
                await bus.drain()
                await bus.stop()
                return state, restart_count, generation
            finally:
                supervisor_module.DEFAULT_WORKER_RESTART_DELAY_SECONDS = original_delay

        state, restart_count, generation = asyncio.run(scenario())
        self.assertEqual(state, "quarantined")
        self.assertGreaterEqual(restart_count, 3)
        self.assertGreaterEqual(generation, 3)


if __name__ == "__main__":
    unittest.main()
