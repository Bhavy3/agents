import asyncio
import unittest

from core.router.intent_router import IntentRouter
from core.router.rules import IntentName, route_by_rules


class RouterTests(unittest.TestCase):
    def test_rules_open_chrome(self) -> None:
        intent = route_by_rules("open chrome")
        self.assertIsNotNone(intent)
        self.assertEqual(intent.name, IntentName.OPEN_CHROME)

    def test_rules_search_google(self) -> None:
        intent = route_by_rules("search google for stable architecture")
        self.assertIsNotNone(intent)
        self.assertEqual(intent.parameters["query"], "stable architecture")

    def test_llm_fallback_stub(self) -> None:
        router = IntentRouter(event_bus=None)  # type: ignore[arg-type]
        intent = asyncio.run(router.route("how are you today"))
        self.assertEqual(intent.name, IntentName.CHAT)


if __name__ == "__main__":
    unittest.main()
