from typing import Any
from ..llm.ollama_client import OllamaClient
from .planner import BoundedPlanner


class PromptPlanner:
    """High-level interface for creating plans from user intent."""

    def __init__(self, ollama_client: OllamaClient):
        self.planner = BoundedPlanner(ollama_client)

    async def create_plan_for_goal(self, goal: str) -> list[dict[str, Any]]:
        """Decomposes a user goal into a list of executable tool steps."""
        # This could include pre-processing context (Vision/Memory) in the future
        steps = await self.planner.plan(goal)
        
        # Ensure we don't have empty plans for simple intents
        if not steps:
            # Fallback for very direct commands
            return []
            
        return steps
