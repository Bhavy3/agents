import logging
import re
from core.orchestrator.attention_state import AttentionStateEngine

class ContextResolver:
    """
    Resolves follow-up references using recent actions, entities, workflows.
    Example: "open it", "continue", "that file" -> Resolved to active task/entity.
    """
    def __init__(self, attention_engine: AttentionStateEngine):
        self.attention = attention_engine
        self.logger = logging.getLogger("orchestrator.context_resolver")
        
        self.reference_keywords = [
            r"\bit\b", r"\bthat\b", r"\bthis\b", r"\bthem\b", 
            r"\bcontinue\b", r"\bdo it\b", r"\bfix it\b", r"\bopen it\b"
        ]

    def contains_reference(self, text: str) -> bool:
        text_lower = text.lower()
        for keyword_pattern in self.reference_keywords:
            if re.search(keyword_pattern, text_lower):
                return True
        return False

    def resolve_references(self, text: str) -> tuple[str, bool, str]:
        """
        Attempts to resolve references in the text.
        Returns (resolved_text, was_resolved, resolved_reference_description).
        """
        if not self.contains_reference(text):
            return text, False, ""
            
        momentum = self.attention.get_current_momentum()
        
        # If momentum is very low, context has decayed too much to reliably resolve
        if momentum < 0.2:
            self.logger.debug("context_decayed_too_much_to_resolve")
            return text, False, ""

        state = self.attention.state
        resolved_desc = ""
        resolved_text = text
        
        # Super simple resolution strategy for phase 12.4
        # Just appends context to the prompt if a reference is found and we have active subjects/entities
        
        context_parts = []
        if state.active_task:
            context_parts.append(f"active task: '{state.active_task}'")
        if state.active_subject:
            context_parts.append(f"active subject: '{state.active_subject}'")
        if state.recent_entities:
            context_parts.append(f"recent entities: {', '.join(state.recent_entities)}")
            
        if context_parts:
            resolved_desc = " | ".join(context_parts)
            # We don't magically rewrite the user's text for the LLM natively yet,
            # we just inject it so the LLM has context of what "it" might refer to.
            resolved_text = f"{text} (Context for references: {resolved_desc})"
            return resolved_text, True, resolved_desc
            
        return text, False, ""
