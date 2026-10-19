import asyncio
import unittest

from core.router.intent_router import IntentRouter
from core.router.rules import IntentName, route_by_rules


class RouterTests(unittest.TestCase):

    def test_current_time_question_uses_local_time_tool(self) -> None:
        intent = route_by_rules("What time is it?")
        self.assertIsNotNone(intent)
        self.assertEqual(intent.name, IntentName.GET_TIME)
        self.assertEqual(intent.parameters, {})

    def test_llm_fallback_stub(self) -> None:
        router = IntentRouter(event_bus=None)  # type: ignore[arg-type]
        intent = asyncio.run(router.route("how are you today"))
        self.assertEqual(intent.name, IntentName.CHAT)


if __name__ == "__main__":
    unittest.main()
