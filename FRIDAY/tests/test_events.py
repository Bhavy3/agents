import asyncio
import unittest

from core.events.bus import EventBus
from core.events.event_types import EventType
from core.events.models import Event
from core.events.models import EventPriority
from core.metrics.metrics import RuntimeMetrics


class EventBusTests(unittest.TestCase):
    def test_publish_dispatches_to_subscriber(self) -> None:
        async def scenario() -> list[str]:
            bus = EventBus()
            received: list[str] = []

            async def handler(event: Event) -> None:
                received.append(event.event_type.value)

            bus.subscribe(EventType.USER_TEXT_RECEIVED, handler)
            await bus.start()
            await bus.publish(Event.create(EventType.USER_TEXT_RECEIVED, {"text": "hello"}))
            await bus.drain()
            await bus.stop()
            return received

        self.assertEqual(asyncio.run(scenario()), [EventType.USER_TEXT_RECEIVED.value])

    def test_queue_overflow_is_counted(self) -> None:
        async def scenario() -> int:
            metrics = RuntimeMetrics()
            bus = EventBus(max_queue_size=1, metrics=metrics)
            async def slow_handler(_: Event) -> None:
                await asyncio.sleep(0.05)

            bus.subscribe(EventType.USER_TEXT_RECEIVED, slow_handler)
            await bus.start()
            for index in range(10):
                await bus.publish_nowait_safe(
                    Event.create(EventType.USER_TEXT_RECEIVED, {"text": str(index)})
                )
            await bus.drain()
            await bus.stop()
            return metrics.dropped_events

        self.assertGreaterEqual(asyncio.run(scenario()), 1)

    def test_stale_event_is_dropped(self) -> None:
        async def scenario() -> int:
            metrics = RuntimeMetrics()
            bus = EventBus(metrics=metrics, event_max_age_seconds=-1.0)
            await bus.start()
            await bus.publish(Event.create(EventType.USER_TEXT_RECEIVED, {"text": "old"}))
            await bus.drain()
            await bus.stop()
            return metrics.dropped_events

        self.assertEqual(asyncio.run(scenario()), 1)

    def test_backpressure_drops_low_priority_events(self) -> None:
        async def scenario() -> int:
            metrics = RuntimeMetrics()
            bus = EventBus(max_queue_size=2, metrics=metrics, high_watermark_ratio=0.0)
            await bus.start()
            await bus.publish_nowait_safe(
                Event.create(
                    EventType.USER_TEXT_RECEIVED,
                    {"text": "low"},
                    priority=EventPriority.LOW,
                )
            )
            await bus.drain()
            await bus.stop()
            return metrics.dropped_events

        self.assertEqual(asyncio.run(scenario()), 1)

    def test_critical_event_bypasses_backpressure_rule(self) -> None:
        async def scenario() -> int:
            metrics = RuntimeMetrics()
            bus = EventBus(max_queue_size=2, metrics=metrics, high_watermark_ratio=0.0)
            received: list[str] = []

            async def handler(event: Event) -> None:
                received.append(event.event_type.value)

            bus.subscribe(EventType.DEADLOCK_WARNING, handler)
            await bus.start()
            await bus.publish_nowait_safe(
                Event.create(
                    EventType.DEADLOCK_WARNING,
                    {"reason": "test"},
                    priority=EventPriority.CRITICAL,
                )
            )
            await bus.drain()
            await bus.stop()
            return len(received)

        self.assertEqual(asyncio.run(scenario()), 1)

    def test_malformed_object_rejected_before_queue_logic(self) -> None:
        async def scenario() -> tuple[int, int, int]:
            metrics = RuntimeMetrics()
            bus = EventBus(max_queue_size=10, metrics=metrics, high_watermark_ratio=0.0)
            malformed_notices: list[Event] = []

            async def handler(event: Event) -> None:
                malformed_notices.append(event)

            bus.subscribe(EventType.MALFORMED_EVENT_DROPPED, handler)
            await bus.start()
            accepted = await bus.publish_nowait_safe("not-an-event")
            await bus.drain()
            queue_depth = bus.queue_depth
            await bus.stop()
            return int(accepted), metrics.dropped_events, len(malformed_notices) + queue_depth

        accepted, dropped, notices = asyncio.run(scenario())
        self.assertEqual(accepted, 0)
        self.assertEqual(dropped, 1)
        self.assertEqual(notices, 1)

    def test_malformed_event_payload_rejected_before_backpressure(self) -> None:
        async def scenario() -> int:
            metrics = RuntimeMetrics()
            bus = EventBus(max_queue_size=10, metrics=metrics, high_watermark_ratio=0.0)
            await bus.start()
            await bus.publish(
                Event(
                    event_type=EventType.USER_TEXT_RECEIVED,
                    payload=None,  # type: ignore[arg-type]
                )
            )
            await bus.drain()
            await bus.stop()
            return metrics.dropped_events

        self.assertEqual(asyncio.run(scenario()), 1)


if __name__ == "__main__":
    unittest.main()
