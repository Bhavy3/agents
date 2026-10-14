from typing import Any, Optional
from ..llm.ollama_client import OllamaClient
from ..tools.tool_registry import ToolRegistry
from .planner import BoundedPlanner


class PromptPlanner:
    """High-level interface for creating plans from user intent."""

    def __init__(self, ollama_client: OllamaClient, tool_registry: Optional[ToolRegistry] = None):
        self.planner = BoundedPlanner(ollama_client, tool_registry=tool_registry)
        self.last_rejection_reason: Optional[str] = None

    async def create_plan_for_goal(self, goal: str) -> list[dict[str, Any]]:
        """Decomposes a user goal into a list of executable tool steps."""
        self.last_rejection_reason = None
        prompt = self.planner._build_prompt(goal)
        try:
            response, metrics = await self.planner.ollama.generate(prompt)
            if not metrics.success or not response:
                self.last_rejection_reason = "llm_error"
                return []
            import json
            clean_json = response.strip()
            if "```json" in clean_json:
                clean_json = clean_json.split("```json")[1].split("```")[0]
            elif "```" in clean_json:
                clean_json = clean_json.split("```")[1].split("```")[0]
            clean_json = clean_json.strip()
            try:
                parsed = json.loads(clean_json)
            except Exception:
                self.last_rejection_reason = "invalid_json"
                return []
            return self.planner.validate_plan(parsed, original_goal=goal)
        except ValueError as ve:
            if "remember_not_authorized" in str(ve):
                self.last_rejection_reason = "remember_not_authorized"
            elif "unsafe_parameter_substitution" in str(ve):
                self.last_rejection_reason = "unsafe_parameter_substitution"
            else:
                self.last_rejection_reason = "invalid_plan"
            return []
        except Exception:
            self.last_rejection_reason = "planning_failed"
            return []
