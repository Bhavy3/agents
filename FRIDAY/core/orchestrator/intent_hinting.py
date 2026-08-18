import logging
from dataclasses import dataclass
from typing import List, Optional
from enum import StrEnum

class ContextDependency(StrEnum):
    ACTIVE_ATTENTION = "active_attention"
    MEMORY = "memory"
    NONE = "none"

@dataclass
class IntentHint:
    intent_hint: str
    confidence: float
    suggested_next_actions: List[str]
    context_dependency: ContextDependency

class PassiveHintEngine:
    """
    Lightweight intent prediction layer. 
    Passive only: does not mutate state or trigger actions.
    """
    def __init__(self):
        self.logger = logging.getLogger("orchestrator.hinting")

    async def generate_hint(self, message: str, attention_owner: Optional[str], history: List[dict]) -> IntentHint:
        """
        Analyze message and attention state to produce a passive prediction hint.
        """
        message_lc = message.lower()
        
        # Default hint
        hint = IntentHint(
            intent_hint="direct_query",
            confidence=0.5,
            suggested_next_actions=["respond"],
            context_dependency=ContextDependency.NONE
        )

        # 1. Heuristic: Check for continuation
        if any(word in message_lc for word in ["more", "continue", "next", "go on"]):
            hint.intent_hint = "continuation_request"
            hint.confidence = 0.8
            hint.suggested_next_actions = ["resume_last_context", "expand_previous"]
            hint.context_dependency = ContextDependency.ACTIVE_ATTENTION

        # 2. Heuristic: Check for tool/file focus
        elif any(word in message_lc for word in ["file", "code", "debug", "fix", "open"]):
            hint.intent_hint = "technical_task"
            hint.confidence = 0.7
            hint.suggested_next_actions = ["read_file", "execute_command", "analyze_stack"]
            hint.context_dependency = ContextDependency.ACTIVE_ATTENTION

        # 3. Heuristic: Check for topic switch
        elif any(word in message_lc for word in ["actually", "wait", "instead", "forget"]):
            hint.intent_hint = "topic_pivot"
            hint.confidence = 0.9
            hint.suggested_next_actions = ["cancel_pending", "switch_context"]
            hint.context_dependency = ContextDependency.NONE

        # 4. Integrate Attention State
        if attention_owner == "workflow":
            hint.context_dependency = ContextDependency.ACTIVE_ATTENTION
            if hint.intent_hint == "direct_query":
                hint.intent_hint = "workflow_clarification"
                hint.confidence = 0.6

        self.logger.info("intent_hint_generated", extra={
            "hint": hint.intent_hint,
            "confidence": hint.confidence
        })
        
        return hint
