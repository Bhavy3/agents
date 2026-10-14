import json
import logging
from typing import Optional
from ..llm.ollama_client import OllamaClient
from ..tools.tool_registry import ToolRegistry

logger = logging.getLogger(__name__)

MAX_WORKFLOW_STEPS = 5

PLANNER_SYSTEM_PROMPT_TEMPLATE = """You are the Workflow Planner for FRIDAY.
Decompose the user's multi-step goal into a short sequence of specific tool calls.
STRICT RULES:
1. At most {max_steps} steps.
2. No recursion or self-replanning.
3. Available tools ONLY:
{available_tools}
4. You can reference previous step results using "{{{{step_N_result}}}}" where N is the zero-based step index.
5. Output ONLY a valid JSON list of step objects with "intent" and "parameters".

Format:
[
  {{"intent": "tool_name", "parameters": {{"param": "value"}}}},
  {{"intent": "another_tool", "parameters": {{"input": "{{{{step_0_result}}}}"}}}}
]"""


import re

PLANNER_REMEMBER_AUTH_TRIGGER = re.compile(
    r"\bremember\s+(?:it|the\s+answer|that|this)\b",
    re.IGNORECASE,
)

# Content-type parameters allowed to receive {{step_N_result}} substitution
ALLOWED_SUBSTITUTION_PARAMS = frozenset({
    "content",
    "text",
    "query",
    "prompt",
    "input",
    "fact",
    "value",
    "data",
})

# Parameters that must NEVER receive substituted output (path, command, app, key)
FORBIDDEN_SUBSTITUTION_PARAMS = frozenset({
    "file_path",
    "path",
    "dir_path",
    "command",
    "app_name",
    "key",
    "keys",
    "hotkey",
    "process_name",
})


class BoundedPlanner:
    """Decomposes goals into a finite, safe sequence of actions validated against ToolRegistry."""

    def __init__(self, ollama_client: OllamaClient, tool_registry: Optional[ToolRegistry] = None):
        self.ollama = ollama_client
        self.registry = tool_registry or ToolRegistry()

    def _build_prompt(self, goal: str) -> str:
        tools = self.registry.list_tools()
        tools_list_str = "\n".join(f"- {t}" for t in sorted(tools))
        sys_prompt = PLANNER_SYSTEM_PROMPT_TEMPLATE.format(
            max_steps=MAX_WORKFLOW_STEPS,
            available_tools=tools_list_str,
        )
        return f"{sys_prompt}\n\nGoal: {goal}\n\nJSON:"

    def validate_plan(self, steps: list, original_goal: Optional[str] = None) -> list[dict]:
        """Strictly validates plan structure, step count, tool availability, and safety constraints."""
        if not isinstance(steps, list):
            raise ValueError(f"Plan must be a JSON list, got {type(steps).__name__}")

        if not steps:
            raise ValueError("Plan cannot be empty")

        if len(steps) > MAX_WORKFLOW_STEPS:
            raise ValueError(
                f"Plan contains {len(steps)} steps, exceeding limit of {MAX_WORKFLOW_STEPS}"
            )

        validated = []
        for i, step in enumerate(steps):
            if not isinstance(step, dict):
                raise ValueError(f"Step {i} must be a dictionary, got {type(step).__name__}")

            intent = step.get("intent")
            if not intent or not isinstance(intent, str):
                raise ValueError(f"Step {i} missing valid 'intent' string")

            if self.registry.get_tool(intent) is None:
                raise ValueError(f"Step {i} requests unknown tool '{intent}'")

            if intent == "remember":
                if not original_goal or not PLANNER_REMEMBER_AUTH_TRIGGER.search(original_goal):
                    logger.error(
                        "planner_remember_rejected",
                        extra={"goal": original_goal, "reason": "Explicit remember authorization trigger required"},
                    )
                    raise ValueError(
                        f"remember_not_authorized: Step {i} requests 'remember' but user utterance does not match remember authorization pattern"
                    )

            params = step.get("parameters", {})
            if not isinstance(params, dict):
                raise ValueError(f"Step {i} 'parameters' must be a dictionary")

            # Validate parameter substitution restrictions: no {{step_N_result}} in path/command/key/app
            for p_name, p_val in params.items():
                if isinstance(p_val, str) and ("{{step_" in p_val):
                    p_lower = p_name.lower()
                    if p_lower in FORBIDDEN_SUBSTITUTION_PARAMS or (p_lower not in ALLOWED_SUBSTITUTION_PARAMS and any(k in p_lower for k in ("path", "file", "cmd", "command", "app", "key"))):
                        logger.error(
                            "planner_unsafe_substitution_rejected",
                            extra={"step": i, "intent": intent, "parameter": p_name, "value": p_val},
                        )
                        raise ValueError(
                            f"unsafe_parameter_substitution: Step {i} ('{intent}') cannot substitute previous step output into restricted parameter '{p_name}'"
                        )

            validated.append({
                "intent": intent,
                "parameters": params,
            })

        return validated

    async def plan(self, goal: str) -> list[dict]:
        """Plans a goal into a validated list of steps. Logs ERROR with exc_info on invalid plans."""
        prompt = self._build_prompt(goal)

        try:
            response, metrics = await self.ollama.generate(prompt)
            if not metrics.success or not response:
                logger.error("planner_generation_failed", extra={"goal": goal})
                return []

            clean_json = response.strip()
            if "```json" in clean_json:
                clean_json = clean_json.split("```json")[1].split("```")[0]
            elif "```" in clean_json:
                clean_json = clean_json.split("```")[1].split("```")[0]
            clean_json = clean_json.strip()

            try:
                parsed = json.loads(clean_json)
            except Exception as e:
                logger.error("planner_invalid_json", exc_info=True, extra={"goal": goal, "raw_response": response})
                return []

            return self.validate_plan(parsed, original_goal=goal)
        except Exception as e:
            logger.error("planner_validation_failed", exc_info=True, extra={"goal": goal, "reason": str(e)})
            return []
