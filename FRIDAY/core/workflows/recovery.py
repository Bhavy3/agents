from typing import Optional
from .state import WorkflowGoal, WorkflowStep, WorkflowStatus


class WorkflowRecovery:
    """Manages error recovery and retry logic for multi-step workflows."""

    def __init__(self, max_retries: int = 2):
        self.max_retries = max_retries

    def evaluate_failure(self, workflow: WorkflowGoal, step: WorkflowStep) -> bool:
        """Determines if a failed step can be retried or if the workflow must fail."""
        
        # Check retry limit
        if step.retry_count >= self.max_retries:
            return False

        # Some errors are fatal (e.g., security rejection, invalid parameters)
        # For now, we allow retries on most common errors (timeout, tool failure)
        if step.error and "forbidden" in step.error.lower():
            return False
            
        return True

    def prepare_retry(self, step: WorkflowStep) -> None:
        """Resets step state for a retry attempt."""
        step.retry_count += 1
        step.status = WorkflowStatus.PENDING
        step.error = None
        step.result = None
