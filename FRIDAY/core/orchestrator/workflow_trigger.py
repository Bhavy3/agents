"""Workflow planning entry point for multi-step conversation turns."""

import re
import time

from core.events.event_types import EventType
from core.events.models import Event

_WORKFLOW_REQUEST = re.compile(
    r"^\s*(?:(?:hey\s+friday|please|can\s+you|could\s+you)\s+)?(?:run|execute|start|trigger|create)\s+(?:a\s+)?workflow\b"
    r"|^\s*(?:(?:hey\s+friday|please|can\s+you|could\s+you)\s+)?(?:debug\s+the\s+project|fix\s+the\s+(?:bug|issue|code|project))\b"
    r"|\b(?:(?:run|execute|start|trigger|create)\s+(?:a\s+)?workflow"
    r"|and\s+remember\s+(?:it|the\s+answer|that))\b"
    r"|\b(?:first|firstly|first\s+off|1[.)])[\s,]+(?:search|look|find|check|open|run|get|read|write|remember|save)\b.*\bthen\b",
    re.IGNORECASE,
)


class WorkflowTriggerMixin:
    """Plans a workflow and publishes its event without owning turn state."""

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
        plan = await self.prompt_planner.create_plan_for_goal(text)
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
        if reason == "remember_not_authorized":
            message = "I couldn't create a plan for that workflow. If you want me to remember something, please state it explicitly."
        elif reason == "unsafe_parameter_substitution":
            message = "I cannot run that workflow because previous step outputs cannot be substituted into sensitive parameters."
        elif reason == "llm_error":
            message = "I was unable to generate a plan right now due to a planner service error."
        else:
            message = "I couldn't create a valid plan for that workflow."

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
