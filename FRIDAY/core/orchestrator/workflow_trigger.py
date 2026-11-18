"""Workflow planning entry point for multi-step conversation turns."""

import re
import time

from core.events.event_types import EventType
from core.events.models import Event
from core.tools.grounding import grounding_refusal, uncovered_domain

_WORKFLOW_REQUEST = re.compile(
    r"^\s*(?:(?:hey\s+friday|please|can\s+you|could\s+you)\s+)?(?:run|execute|start|trigger|create)\s+(?:a\s+)?workflow\b"
    r"|\b(?:build|make|create|run|execute|start|trigger|automate|set\s+up)\b.{0,40}\bworkflow\b"
    r"|^\s*(?:(?:hey\s+friday|please|can\s+you|could\s+you)\s+)?(?:debug\s+the\s+project|fix\s+the\s+(?:bug|issue|code|project))\b"
    r"|\b(?:(?:run|execute|start|trigger|create)\s+(?:a\s+)?workflow"
    r"|and\s+remember\s+(?:it|the\s+answer|that))\b"
    r"|\b(?:build|built|bilt|bult|create|creat|make|develop|implement|scaffold|set\s+up|start|begin|give|generate|work\s+on)\b.{0,180}\b(?:project|website|web\s+site|site|app|application|folder|directory|file|files|blueprint|blue\s+print|research|coding|code)\b"
    r"|\b(?:blueprint|blue\s+print|folder\s+structure|folder\s+strucher|project\s+files?)\b.{0,120}\b(?:create|build|make|give|generate|start|work|code|implement)\b"
    r"|\b(?:research|reserch)\b.{0,180}\b(?:blueprint|blue\s+print|file|files|folder)\b"
    r"|\b(?:start|begin|continue)\s+(?:the\s+)?(?:coding|code|implementation|development|work)\b"
    r"|\b(?:first|firstly|first\s+off|1[.)])[\s,]+(?:search|look|find|check|open|run|get|read|write|remember|save)\b.*\bthen\b",
    re.IGNORECASE,
)


def refusal_message(reason: str | None, detail: str | None = None) -> str:
    """Turn a planning failure into a sentence the user can act on.

    An empty plan means no tool can serve the request; saying so plainly is
    better than a vague "couldn't create a valid plan".
    """
    if reason == "impossible":
        return f"I cannot perform that task: {detail}" if detail else "I don't have the capability to perform that task."
    if reason == "remember_not_authorized":
        return (
            "I couldn't create a plan for that workflow. If you want me to "
            "remember something, please state it explicitly."
        )
    if reason == "unsafe_parameter_substitution":
        return (
            "I cannot run that workflow because previous step outputs cannot be "
            "substituted into sensitive parameters."
        )
    if reason == "llm_error":
        return "I was unable to generate a plan right now due to a planner service error."
    if detail and "cannot be empty" in detail:
        return "I don't have a tool that can do that yet, so I did not guess at a plan."
    if detail:
        return f"I couldn't create a valid plan for that workflow: {detail}"
    return "I couldn't create a valid plan for that workflow."


class WorkflowTriggerMixin:
    """Plans a workflow and publishes its event without owning turn state."""

    async def _try_refuse_uncovered_capability(
        self,
        text: str,
        turn_id: str,
        correlation_id: str | None,
        start_time: float,
    ) -> bool:
        """Refuse a private-data request no capability can serve.

        Runs before planning: an honest "I can't" from here is better than a
        confident answer invented by the chat model.
        """
        from ..tools.grounding import destructive_refusal, destructive_request

        domain = uncovered_domain(text)
        message: str | None = None
        if domain is not None:
            message = grounding_refusal(domain)
            self.logger.info(
                "capability_grounding_refused",
                extra={"domain": domain, "turn_id": turn_id},
            )
        else:
            # Destructive work outside the workspace cannot be undone, so it is
            # refused before any planning rather than attempted and failed.
            destructive = destructive_request(text)
            if destructive is not None:
                message = destructive_refusal(destructive)
                self.logger.info(
                    "destructive_request_refused",
                    extra={"reason": destructive, "turn_id": turn_id},
                )
        if message is None:
            return False
        await self.event_bus.publish(Event.create(
            EventType.RESPONSE_READY,
            {"text": message, "turn_id": turn_id},
            self.name,
            correlation_id,
        ))
        await self.event_bus.publish(Event.create(
            EventType.CONVERSATION_TURN_ENDED,
            {"turn_id": turn_id, "duration": round(time.perf_counter() - start_time, 3)},
            self.name,
            correlation_id,
        ))
        return True

    async def _try_start_workflow(
        self,
        text: str,
        turn_id: str,
        correlation_id: str | None,
        start_time: float,
    ) -> bool:
        if not self.prompt_planner or not _WORKFLOW_REQUEST.search(text):
            return False

        self.logger.info("attempting_workflow_planning", extra={"goal": text})
        try:
            plan = await self.prompt_planner.create_plan_for_goal(text)
        except Exception:
            self.logger.exception(
                "workflow_planning_failed",
                extra={"turn_id": turn_id, "goal": text},
            )
            return False
        if plan:
            self.logger.info("workflow_plan_generated", extra={"steps": len(plan)})
            # Preserve the historical app import performed on accepted plans.
            from core.app import FridayApp  # noqa: F401

            if correlation_id:
                self._pending_workflow_correlations.add(correlation_id)
            await self.event_bus.publish(Event.create(
                EventType.ACTION_GRAPH_STARTED,
                {"goal": text, "steps": plan},
                self.name,
                correlation_id,
            ))
            return True

        reason = getattr(self.prompt_planner, "last_rejection_reason", None)
        if reason in {"llm_error", "planning_failed"}:
            self.logger.error(
                "workflow_planning_failed",
                extra={"turn_id": turn_id, "reason": reason},
            )
            return False
        message = refusal_message(
            reason,
            getattr(self.prompt_planner, "last_rejection_detail", None),
        )

        await self.event_bus.publish(Event.create(
            EventType.RESPONSE_READY,
            {"text": message, "turn_id": turn_id},
            self.name,
            correlation_id,
        ))
        await self.event_bus.publish(Event.create(
            EventType.CONVERSATION_TURN_ENDED,
            {"turn_id": turn_id, "duration": round(time.perf_counter() - start_time, 3)},
            self.name,
            correlation_id,
        ))
        return True
