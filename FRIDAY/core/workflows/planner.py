import inspect
import json
import logging
from typing import Optional
from ..llm.ollama_client import OllamaClient
from ..tools.tool_registry import ToolRegistry

logger = logging.getLogger(__name__)

MAX_WORKFLOW_STEPS = 5

_PARAMETER_ALIASES = {
    "search_web": {"input": "query"},
    "research_web": {"input": "query"},
    "remember": {"input": "fact"},
    "write_text_file": {"path": "file_path", "text": "content"},
    "read_text_file": {"path": "file_path"},
    "browser_click": {"locator": "selector", "value": "selector"},
    "browser_type": {"locator": "selector", "value": "text"},
    "desktop_type": {"value": "text"},
}
_REQUIRED_PARAMETERS = {
    "write_text_file": {"file_path", "content"},
    "read_text_file": {"file_path"},
    "open_url": {"url"},
    "search_web": {"query"},
    "research_web": {"query"},
    "browser_open": {"url"},
    "browser_click": {"selector"},
    "browser_type": {"selector", "text"},
    "desktop_snapshot": {"app"},
    "desktop_find": {"app", "text"},
    "desktop_click": {"ref"},
    "desktop_type": {"ref", "text"},
    "desktop_launch": {"app"},
    "execute_shell": {"command"},
    "memory_recall": {"query"},
    "n8n_create_workflow": {"name"},
}

PLANNER_SYSTEM_PROMPT_TEMPLATE = """You are the Workflow Planner for FRIDAY.
Decompose the user's multi-step goal into a short sequence of specific tool calls.
Act on build, coding, research, and file-generation requests immediately. Do not
ask a follow-up question or return prose. For project files, use relative paths
under the current workspace and use write_text_file; parent directories are
created automatically.
STRICT RULES:
1. At most {max_steps} steps.
2. No recursion or self-replanning.
3. Available tools ONLY. Use exact parameter names:
{available_tools}
write_text_file: file_path, content
read_text_file: file_path
execute_shell: command, directory, timeout_seconds
browser_open: url; browser_snapshot: no parameters
browser_click: selector; browser_type: selector, text
desktop_snapshot: app, optional window_id; desktop_find: app, text
desktop_click: ref; desktop_type: ref, text; desktop_launch: app
For project or website builds, write files directly. Do not open GitHub,
click websites, or invent browser steps unless explicitly requested. Do not use
remember unless the user explicitly asks to remember something.
When you write a web page: put it in a folder named after the subject (for
example food/index.html, not index.html at the root); write complete, valid
HTML with a <link rel="stylesheet" href="style.css"> when you also write that
stylesheet; and write real copy for the subject - a heading, an intro
paragraph and at least three list items. Never write a one-line placeholder.
4. Use each tool only within its stated domain. search_web and research_web read
   the PUBLIC web only: they can never read the user's private email, inbox,
   messages or local files. If the user's goal cannot be served by any available tool,
   do not substitute an unrelated tool: return [] or output an impossible refusal object:
   {{"impossible": true, "reason": "<clear explanation of why this goal cannot be fulfilled>"}}
5. You can reference previous step results using "{{{{step_N_result}}}}" where N is the zero-based step index.
6. Output ONLY a valid JSON list of step objects with "intent" and "parameters", or an impossible refusal object:
   {{"impossible": true, "reason": "why the goal cannot be achieved with available tools"}}

Format:
[
  {{"intent": "tool_name", "parameters": {{"param": "value"}}}},
  {{"intent": "another_tool", "parameters": {{"input": "{{{{step_0_result}}}}"}}}}
]
OR if impossible:
{{"impossible": true, "reason": "why the goal cannot be achieved with available tools"}}"""


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

    def _build_prompt(self, goal: str, skill_context: str = "") -> str:
        tools = self.registry.list_tools()
        tools_list_str = "\n".join(f"- {t}" for t in sorted(tools))
        sys_prompt = PLANNER_SYSTEM_PROMPT_TEMPLATE.format(
            max_steps=MAX_WORKFLOW_STEPS,
            available_tools=tools_list_str,
        )
        skill_block = f"\n\nRelevant skill instructions:\n{skill_context}" if skill_context else ""
        return f"{sys_prompt}{skill_block}\n\nGoal: {goal}\n\nJSON:"

    def _signature_missing_parameters(self, intent: str, params: dict) -> list[str]:
        """Return required parameters the step omitted, read from the tool itself."""
        func = self.registry.get_tool(intent)
        if func is None:
            return []
        try:
            signature = inspect.signature(func)
        except (TypeError, ValueError):
            logger.warning("planner_signature_unavailable", extra={"tool": intent})
            return []
        missing: list[str] = []
        for name, parameter in signature.parameters.items():
            if name in ("self", "cls"):
                continue
            if parameter.kind in (parameter.VAR_POSITIONAL, parameter.VAR_KEYWORD):
                continue
            if parameter.default is not parameter.empty:
                continue
            if not str(params.get(name, "")).strip():
                missing.append(name)
        return missing

    def validate_plan(self, steps: list | dict, original_goal: Optional[str] = None) -> list[dict]:
        """Strictly validates plan structure, step count, tool availability, and safety constraints."""
        if isinstance(steps, dict):
            if steps.get("impossible") is True:
                reason = str(steps.get("reason") or "Goal cannot be fulfilled with available tools").strip()
                raise ValueError(f"impossible: {reason}")
            raise ValueError(f"Plan must be a JSON list, got dict")

        if not isinstance(steps, list):
            raise ValueError(f"Plan must be a JSON list, got {type(steps).__name__}")

        if len(steps) == 1 and isinstance(steps[0], dict) and steps[0].get("impossible") is True:
            reason = str(steps[0].get("reason") or "Goal cannot be fulfilled with available tools").strip()
            raise ValueError(f"impossible: {reason}")

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
            params = dict(params)
            for source_name, target_name in _PARAMETER_ALIASES.get(intent, {}).items():
                if source_name in params and target_name not in params:
                    params[target_name] = params.pop(source_name)
            missing = sorted(
                name for name in _REQUIRED_PARAMETERS.get(intent, set())
                if not str(params.get(name, "")).strip()
            )
            if not missing and intent not in _REQUIRED_PARAMETERS:
                # The table above drifts behind the tools: `open_section`
                # required `url` while nothing declared it, so the plan was
                # accepted and then failed at execution time.
                missing = self._signature_missing_parameters(intent, params)
            if missing:
                raise ValueError(
                    f"Step {i} ('{intent}') is missing required parameter(s): {', '.join(missing)}"
                )
            if (
                original_goal
                and re.search(r"\b(?:build|create|make|develop|implement|scaffold)\b", original_goal, re.I)
                and re.search(r"\b(?:project|website|web\s+site|site|app|application)\b", original_goal, re.I)
                and intent.startswith(("browser_", "desktop_"))
                and not re.search(r"\b(?:open|navigate|click|type|browser|desktop)\b", original_goal, re.I)
                and not (
                    intent == "browser_open"
                    and str(params.get("url", "")).startswith("workspace://")
                )
                and not (intent == "browser_snapshot" and "website" in original_goal.casefold())
            ):
                raise ValueError(
                    f"Step {i} ('{intent}') is not appropriate for a build request; write project files directly"
                )
            if (
                original_goal
                and intent in {"browser_click", "browser_type"}
                and re.search(r"\b(?:navigate|open)\b", original_goal, re.I)
                and re.search(r"\b(?:title|page\s+name)\b", original_goal, re.I)
            ):
                raise ValueError(
                    f"Step {i} ('{intent}') is unnecessary for a read-only page-title request"
                )
            if intent == "n8n_create_workflow":
                # A name is not an automation. Without a node the API creates
                # an empty workflow, which verifies as HTTP 200 and means
                # nothing -- reject it so the deterministic plan can run.
                raw_workflow = params.get("workflow_json")
                parsed_workflow = None
                if isinstance(raw_workflow, dict):
                    parsed_workflow = raw_workflow
                elif isinstance(raw_workflow, str) and raw_workflow.strip():
                    try:
                        parsed_workflow = json.loads(raw_workflow)
                    except (TypeError, ValueError):
                        parsed_workflow = None
                if not isinstance(parsed_workflow, dict) or not parsed_workflow.get("nodes"):
                    raise ValueError(
                        f"Step {i} ('n8n_create_workflow') needs workflow_json with at least one node"
                    )
            if intent == "search_web" and "query" not in params and isinstance(params.get("input"), str):
                params["query"] = params.pop("input")
                logger.warning(
                    "planner_search_query_alias_normalized",
                    extra={"step": i, "source_parameter": "input"},
                )
            if intent == "remember" and "fact" not in params and isinstance(params.get("input"), str):
                params["fact"] = params.pop("input")
                logger.warning(
                    "planner_remember_fact_alias_normalized",
                    extra={"step": i, "source_parameter": "input"},
                )
            remember_value = params.get("fact")
            remember_reference = (
                re.fullmatch(r"\{\{step_(\d+)_(?:result|output)\}\}", remember_value.strip())
                if isinstance(remember_value, str)
                else None
            )
            invalid_forward_reference = bool(remember_reference and int(remember_reference.group(1)) >= i)
            if (
                intent == "remember"
                and (
                    "fact" not in params
                    or params.get("fact") is None
                    or isinstance(params.get("fact"), str) and not params["fact"].strip()
                    or invalid_forward_reference
                )
                and i > 0
                and validated[i - 1]["intent"] == "search_web"
                and original_goal
                and PLANNER_REMEMBER_AUTH_TRIGGER.search(original_goal)
            ):
                params["fact"] = f"{{{{step_{i - 1}_result}}}}"
                logger.warning(
                    "planner_empty_remember_fact_uses_previous_search",
                    extra={"step": i, "source_step": i - 1},
                )

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

    async def plan(self, goal: str, skill_context: str = "") -> list[dict]:
        """Plans a goal into a validated list of steps. Logs ERROR with exc_info on invalid plans."""
        prompt = self._build_prompt(goal, skill_context=skill_context)

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
