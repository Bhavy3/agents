"""Adaptive Intelligence Router: 3B vs 7B routing decisions based on complexity and latency budget."""

import logging
from typing import Any, Tuple

from core.router.complexity_detector import detect_query_complexity
from core.router.latency_predictor import estimate_latency, infer_latency_budget

logger = logging.getLogger("core.router.adaptive_router")
INTERACTIVE_COMPLEXITY_LATENCY_CAP_SECONDS = 12.0


class AdaptiveRouter:
    def __init__(self, model_manager: Any = None):
        self.model_manager = model_manager

    def _seven_b_is_warm(self) -> bool:
        """Return whether escalation can avoid a model cold-start penalty."""
        if self.model_manager is None:
            # A pure routing decision has no process-health information.
            return True
        processes = getattr(self.model_manager, "model_processes", None)
        if not isinstance(processes, dict) or "7b" not in processes:
            # Preserve compatibility with lightweight manager doubles and
            # direct callers that do not expose process state.
            return True
        readiness = getattr(self.model_manager, "model_ready", None)
        if isinstance(readiness, dict) and "7b" in readiness:
            return bool(readiness["7b"]) and processes.get("7b") is not None
        return processes.get("7b") is not None

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
            # Quality is the default for multilayer work.  Only an explicit
            # urgency request or an objectively excessive predicted wait is
            # allowed to keep a complex request on 3B. This avoids paying a
            # cold 7B startup for requests whose predicted generation alone
            # would exceed an interactive response window.
            urgent = any(token in utterance.lower() for token in ("quick", "asap", "fast", "immediate", "right now"))
            if not urgent or latency_7b <= latency_budget:
                if (
                    latency_7b <= INTERACTIVE_COMPLEXITY_LATENCY_CAP_SECONDS
                    or self._seven_b_is_warm()
                ):
                    return ("7b", "complex_query_needs_7b")
                return ("3b", "complex_query_exceeds_interactive_cap_use_3b_fast")
            return ("3b", "complex_query_urgent_use_3b_fast")

    async def route(self, utterance: str) -> Tuple[str, str]:
        """Select a model and activate it when a model manager is available."""
        target_model, reason = await self.decide_model(utterance)
        active_model = target_model

        if self.model_manager and target_model != self.model_manager.current_model:
            await self.model_manager.switch_model(target_model, reason)
            # The manager's reported active model is the source of truth.  A
            # truthy/implicit switch result alone does not prove that the
            # single backend server is now serving the selected model.
            active_model = self.model_manager.current_model
            if active_model != target_model:
                reason = f"{reason}; switch_failed_fallback_{active_model}"

        if self.model_manager is None:
            logger.info(f"routing_selected: model={active_model}, reason={reason}")
        else:
            logger.info(f"routing_executed: model={active_model}, reason={reason}")
        return active_model, reason
