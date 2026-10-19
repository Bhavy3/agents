"""Adaptive Intelligence Router: 3B vs 7B routing decisions based on complexity and latency budget."""

import logging
from typing import Any, Tuple

from core.router.complexity_detector import detect_query_complexity
from core.router.latency_predictor import estimate_latency, infer_latency_budget

logger = logging.getLogger("core.router.adaptive_router")


class AdaptiveRouter:
    def __init__(self, model_manager: Any = None):
        self.model_manager = model_manager

    async def decide_model(self, utterance: str) -> Tuple[str, str]:
        """Decide 3B vs 7B. Returns (model, reason)."""
        complexity = detect_query_complexity(utterance)
        latency_budget = infer_latency_budget(utterance)

        latency_3b = estimate_latency(utterance, "3b")
        latency_7b = estimate_latency(utterance, "7b")

        logger.info(
            f"routing_decision: complexity={complexity}, budget={latency_budget}s, "
            f"est_3b={latency_3b:.2f}s, est_7b={latency_7b:.2f}s"
        )

        # Decision tree
        if complexity == "simple":
            return ("3b", "simple_query")
        elif complexity == "medium":
            if latency_3b <= latency_budget:
                return ("3b", "medium_query_fits_budget")
            else:
                return ("7b", "medium_query_exceeds_budget")
        else:  # complex
            if latency_7b <= latency_budget:
                return ("7b", "complex_query_needs_7b")
            else:
                # User wants fast answer on complex query: tradeoff
                return ("3b", "complex_query_urgent_use_3b_fast")

    async def route(self, utterance: str) -> Tuple[str, str]:
        """Execute routing decision."""
        target_model, reason = await self.decide_model(utterance)
        active_model = target_model

        if self.model_manager and target_model != self.model_manager.current_model:
            switched = await self.model_manager.switch_model(target_model, reason)
            if switched is False:
                active_model = self.model_manager.current_model
                reason = f"{reason}; switch_failed_fallback_{active_model}"

        logger.info(f"routing_executed: model={active_model}, reason={reason}")
        return active_model, reason
