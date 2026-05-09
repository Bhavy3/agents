import asyncio
import unittest

from core.events.bus import EventBus
from core.events.event_types import EventType
from core.events.models import Event
from core.executor.command_registry import CommandRegistry
from core.executor.dry_run_actions import ExecutorResult
from core.executor.executor import CommandExecutor
from core.router.rules import IntentName
from plugins.chrome.plugin import register as register_chrome


class ExecutorTests(unittest.TestCase):
    def test_executor_emits_response(self) -> None:
        async def scenario() -> str:
            bus = EventBus()
            registry = CommandRegistry()
            async def help_handler(_: dict) -> ExecutorResult:
                return ExecutorResult(True, "Dry-run help")
            registry.register(IntentName.HELP.value, help_handler)
            executor = CommandExecutor(bus, registry)
            responses: list[str] = []

            async def handle_response(event: Event) -> None:
                responses.append(str(event.payload["text"]))

            bus.subscribe(EventType.RESPONSE_READY, handle_response)
            await bus.start()
            await executor.start()
            await asyncio.sleep(0.1)
            await bus.publish(
                Event.create(
                    EventType.ACTION_REQUESTED,
                    {"action_id": "act_ok", "intent": IntentName.HELP.value, "parameters": {}},
                )
            )
            await bus.drain()
            await asyncio.sleep(0.1)
            await executor.stop()
            await bus.stop()
            return responses[0]

        self.assertIn("Dry-run", asyncio.run(scenario()))

    def test_invalid_command_is_blocked_and_recorded(self) -> None:
        async def scenario() -> tuple[bool, bool]:
            bus = EventBus()
            registry = CommandRegistry()
            executor = CommandExecutor(bus, registry)
            await bus.start()
            await executor.start()
            await asyncio.sleep(0.1)
            await bus.publish(
                Event.create(
                    EventType.ACTION_REQUESTED,
                    {"action_id": "test_act", "intent": "delete_everything", "parameters": {}},
                )
            )
            await bus.drain()
            await asyncio.sleep(0.1)
            await executor.stop()
            await bus.stop()
            last_command = executor.command_history.last_command
            return (
                last_command is not None and not last_command.success,
                last_command is not None and last_command.metadata.get("requires_confirmation", False),
            )

        blocked, requires_confirmation = asyncio.run(scenario())
        self.assertTrue(blocked)
        self.assertTrue(requires_confirmation)

    def test_plugin_failure_is_isolated(self) -> None:
        async def scenario() -> tuple[str, int]:
            bus = EventBus()
            registry = CommandRegistry()

            async def failing_handler(_: dict[str, str]) -> ExecutorResult:
                raise RuntimeError("plugin exploded")

            registry.register(IntentName.HELP.value, failing_handler)
            executor = CommandExecutor(bus, registry)
            errors: list[str] = []

            async def handle_error(event: Event) -> None:
                errors.append(str(event.payload["component"]))

            bus.subscribe(EventType.ERROR_OCCURRED, handle_error)
            await bus.start()
            await executor.start()
            await asyncio.sleep(0.1)
            await bus.publish(
                Event.create(
                    EventType.ACTION_REQUESTED,
                    {"action_id": "act_fail", "intent": IntentName.HELP.value, "parameters": {}},
                )
            )
            await bus.drain()
            await asyncio.sleep(0.1)
            await executor.stop()
            await bus.stop()
            last_command = executor.command_history.last_command
            return (last_command.result if last_command else "", len(errors))

        message, error_count = asyncio.run(scenario())
        self.assertIn("encountered an error", message)
        self.assertEqual(error_count, 1)


if __name__ == "__main__":
    unittest.main()
