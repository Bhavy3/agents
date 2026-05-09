import asyncio
import unittest

from core.events.bus import EventBus
from core.events.event_types import EventType
from core.events.models import Event
from core.executor.command_registry import CommandRegistry
from core.executor.executor import CommandExecutor
from core.router.intent_router import IntentRouter
from plugins.browser.plugin import register as register_browser
from plugins.chrome.plugin import register as register_chrome
from plugins.files.plugin import register as register_files
from plugins.system.plugin import register as register_system


class StressTests(unittest.TestCase):
    def test_event_flood_survives(self) -> None:
        async def scenario() -> int:
            bus = EventBus(max_queue_size=2000)
            count = 0

            async def handler(_: Event) -> None:
                nonlocal count
                count += 1

            bus.subscribe(EventType.USER_TEXT_RECEIVED, handler)
            await bus.start()
            for index in range(1000):
                await bus.publish(
                    Event.create(
                        EventType.USER_TEXT_RECEIVED,
                        {"text": f"help {index}"},
                    )
                )
            await bus.drain()
            await bus.stop()
            return count

        self.assertEqual(asyncio.run(scenario()), 1000)

    def test_malformed_events_are_dropped_without_crash(self) -> None:
        async def scenario() -> bool:
            bus = EventBus()
            await bus.start()
            await bus.publish("not-an-event")  # type: ignore[arg-type]
            await bus.publish(
                Event(
                    event_type=EventType.USER_TEXT_RECEIVED,
                    payload=None,  # type: ignore[arg-type]
                )
            )
            await bus.drain()
            await bus.stop()
            return True

        self.assertTrue(asyncio.run(scenario()))

    def test_router_executor_loop_handles_mixed_commands(self) -> None:
        async def scenario() -> list[str]:
            bus = EventBus()
            registry = CommandRegistry()
            register_chrome(registry)
            register_files(registry)
            register_browser(registry)
            register_system(registry)
            router = IntentRouter(bus)
            executor = CommandExecutor(bus, registry)
            responses: list[str] = []

            async def handle_response(event: Event) -> None:
                responses.append(str(event.payload["text"]))

            bus.subscribe(EventType.RESPONSE_READY, handle_response)
            await bus.start()
            await router.start()
            await executor.start()
            await asyncio.sleep(0.1) # Wait for subscription
            
            for text in (
                "open chrome",
                "open folder C:\\tmp",
                "search google for asyncio queues",
                "exit",
                "help",
            ):
                await router.handle_user_text(Event.create(EventType.USER_TEXT_RECEIVED, {"text": text}))
            
            await bus.drain()
            
            # Wait for responses since they are emitted from async tasks
            for _ in range(30):
                if len(responses) >= 5:
                    break
                await asyncio.sleep(0.1)
                
            await executor.stop()
            if executor._task:
                try:
                    await asyncio.wait_for(executor._task, timeout=2.0)
                except asyncio.TimeoutError:
                    pass
                    
            await bus.stop()
            return responses

        responses = asyncio.run(scenario())
        self.assertEqual(len(responses), 5)
        self.assertTrue(any("Dry-run" in response for response in responses))
        self.assertTrue(any("Dry-run" in response for response in responses))

    def test_runtime_metrics_track_processing(self) -> None:
        async def scenario() -> int:
            from core.metrics.metrics import RuntimeMetrics

            metrics = RuntimeMetrics()
            bus = EventBus(metrics=metrics)

            async def handler(_: Event) -> None:
                return None

            bus.subscribe(EventType.HEALTHCHECK, handler)
            await bus.start()
            await bus.publish(Event.create(EventType.HEALTHCHECK, {}))
            await bus.drain()
            await bus.stop()
            return metrics.processed_events

        self.assertEqual(asyncio.run(scenario()), 1)
