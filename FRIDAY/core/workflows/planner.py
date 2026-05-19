import json
from typing import Optional
from ..llm.ollama_client import OllamaClient
from .state import WorkflowStep


PLANNER_SYSTEM_PROMPT = """You are the Workflow Planner for FRIDAY.
Decompose the user's goal into a sequence of specific tool calls.
STRICT RULES:
1. Max 5 steps.
2. No recursion or self-replanning.
3. Use only available tools: open_chrome, open_folder, search_google, read_file, write_file, launch_app.
4. You can reference previous step results using "{{step_N_result}}" where N is the zero-based step index.
5. Output ONLY a JSON list of steps.

Format:
[
  {"intent": "tool_name", "parameters": {"param": "value"}},
  {"intent": "another_tool", "parameters": {"input": "{{step_0_result}}"}}
]"""


class BoundedPlanner:
    """Decomposes goals into a finite, safe sequence of actions."""

    def __init__(self, ollama_client: OllamaClient):
        self.ollama = ollama_client

    async def plan(self, goal: str) -> list[dict]:
        prompt = f"{PLANNER_SYSTEM_PROMPT}\n\nGoal: {goal}\n\nJSON:"
        
        response, metrics = await self.ollama.generate(prompt)
        
        if not metrics.success or not response:
            return []

        try:
            # Clean response if LLM adds markdown
            clean_json = response.strip()
            if "```json" in clean_json:
                clean_json = clean_json.split("```json")[1].split("```")[0]
            elif "```" in clean_json:
                clean_json = clean_json.split("```")[1].split("```")[0]
                
            steps = json.loads(clean_json)
            
            if not isinstance(steps, list):
                return []
                
            # Enforce hard limit
            return steps[:5]
        except Exception:
            return []
