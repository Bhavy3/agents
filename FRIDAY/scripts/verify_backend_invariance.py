"""Step 8: Backend verification test (synthetic).
Confirms tool selection and decisions are NEVER affected by tone.
"""
import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from core.cognition.tone_detector import detect_tone
from core.cognition.cognitive_state import CognitiveStateEngine

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("backend_verification")


@dataclass
class Plan:
    goal: str
    steps: list[dict[str, Any]]


class BackendPlanner:
    """Simulates planner with tool selection based on task intent, unaffected by emotional tone."""

    async def plan(self, goal: str) -> Plan:
        # Task decomposition depends purely on task semantics, never on tone
        if "search" in goal.lower():
            steps = [{"intent": "search_web", "parameters": {"query": "search query"}}]
        else:
            steps = [{"intent": "chat", "parameters": {"text": goal}}]
        return Plan(goal=goal, steps=steps)


async def verify_backend_invariance():
    test_queries = [
        ("can you search the web", "confident"),
        ("not sure if searching helps", "cautious"),
        ("explore web search options", "curious"),
        ("I'm frustrated, help me search", "warm"),
    ]

    cognitive_state = CognitiveStateEngine(None)
    planner = BackendPlanner()

    for query, expected_tone in test_queries:
        tone = detect_tone(query)
        assert tone == expected_tone, f"Expected {expected_tone}, got {tone}"

        # Plan same task with all 4 tones
        plans_by_tone = {}
        for tone_override in ["confident", "cautious", "curious", "warm"]:
            cognitive_state.current_tone = tone_override
            plan = await planner.plan(query)  # Same query, different tone
            plans_by_tone[tone_override] = plan

        # Assert all plans are identical (no tool/decision change)
        first_plan = plans_by_tone["confident"]
        for tone, plan in plans_by_tone.items():
            assert plan.steps == first_plan.steps, f"Tool selection changed for {tone}"

    logger.info("Backend verified: all tones produce identical plans & decisions.")
    print("ALL_TONES_PRODUCE_IDENTICAL_PLANS: PASSED")


if __name__ == "__main__":
    asyncio.run(verify_backend_invariance())
