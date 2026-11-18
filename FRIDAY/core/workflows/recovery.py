from typing import Any, Optional
from .state import WorkflowGoal, WorkflowStep, WorkflowStatus

# Idempotent (read-only) tools that are safe to retry on transient failure
IDEMPOTENT_TOOLS: frozenset[str] = frozenset({
    "search_web",
    "read_text_file",
    "list_dir",
    "search_files",
})


class WorkflowRecovery:
    """Manages error recovery and retry logic for multi-step workflows."""

    def __init__(
        self,
        max_retries: int = 2,
        base_backoff_seconds: float = 1.0,
        capabilities: dict[str, Any] | None = None,
    ):
        self.max_retries = max_retries
        self.base_backoff_seconds = base_backoff_seconds
        if capabilities is not None:
            self.capabilities = capabilities
        else:
            try:
                from ..tools.capability_loader import CapabilityLoader
                self.capabilities = CapabilityLoader().load_all()
            except Exception:
                self.capabilities = {}

    def is_idempotent(self, intent: str) -> bool:
        """Determines if a tool intent is idempotent (read-only) and safe to retry."""
        return intent in IDEMPOTENT_TOOLS

    def is_retry_safe(self, intent: str) -> bool:
        cap = self.capabilities.get(intent)
        if cap is not None:
            return bool(getattr(cap, "retry_safe", False))
        return self.is_idempotent(intent)

    def get_backoff_delay(self, step: WorkflowStep) -> float:
        """Calculates exponential backoff delay based on retry count."""
        # For first retry (retry_count=1): 2^0 = 1.0 * base
        exp = max(0, step.retry_count - 1)
        return self.base_backoff_seconds * (2 ** exp)

    def evaluate_failure(self, workflow: WorkflowGoal, step: WorkflowStep) -> bool:
        """Determines if a failed step can be retried or if the workflow must fail."""
        # Check retry limit
        if step.retry_count >= self.max_retries:
            return False

        # Denials / security rejections are non-retryable
        if step.error and any(k in step.error.lower() for k in ("forbidden", "denied", "refused", "user_refused")):
            return False

        # On verification failure, strictly check capability's retry_safe attribute
        is_verification_failure = "verification failed" in (step.error or "").lower()
        if is_verification_failure:
            cap = self.capabilities.get(step.intent)
            if cap is not None:
                return bool(getattr(cap, "retry_safe", False))
            return self.is_idempotent(step.intent)

        # Standard failure: check capability retry_safe or idempotent allowlist
        cap = self.capabilities.get(step.intent)
        if cap is not None and getattr(cap, "retry_safe", False):
            return True

        return self.is_idempotent(step.intent)

    def prepare_retry(self, step: WorkflowStep) -> None:
        """Resets step state for a retry attempt."""
        step.retry_count += 1
        step.status = WorkflowStatus.PENDING
        step.error = None
        step.result = None
