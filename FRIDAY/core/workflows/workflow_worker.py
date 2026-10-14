import asyncio
from ..workers.base_worker import BaseWorker
from ..events.bus import EventBus
from ..events.event_types import EventType
from ..events.models import Event
from .workflow_engine import WorkflowEngine
from .recovery import WorkflowRecovery
from .store import WorkflowStore
from .state import WorkflowStatus


class WorkflowWorker(BaseWorker):
    """Integrates workflow management into the global event system."""

    def __init__(self, event_bus: EventBus):
        super().__init__("workflow_worker", event_bus)
        self.engine = WorkflowEngine(event_bus)
        self.recovery = WorkflowRecovery()
        self.store = WorkflowStore()
        self._retry_tasks: dict[str, asyncio.Task] = {}
        
        # Load any existing workflows from store on startup
        self.engine.active_workflows = self.store.load_workflows()

        self.event_bus.subscribe(EventType.ACTION_COMPLETED, self.handle_action_completed)
        self.event_bus.subscribe(EventType.ACTION_FAILED, self.handle_action_failed)
        self.event_bus.subscribe(EventType.ACTION_DENIED, self.handle_action_denied)
        self.event_bus.subscribe(EventType.ACTION_GRAPH_STARTED, self.handle_workflow_request)
        self.event_bus.subscribe(EventType.CONVERSATION_INTERRUPTED, self.handle_interrupted)

    async def run(self) -> None:
        await super().run()

    async def handle_workflow_request(self, event: Event) -> None:
        goal = event.payload.get("goal", "unnamed workflow")
        steps = event.payload.get("steps", [])
        if not steps:
            return
            
        workflow_id = await self.engine.create_workflow(goal, steps)
        self.logger.info("workflow_initiated", extra={"workflow_id": workflow_id, "goal": goal})
        await self.engine.start_workflow(workflow_id)

    async def work(self) -> None:
        while not self.should_stop:
            # Heartbeat with active workflow count
            active_count = sum(1 for w in self.engine.active_workflows.values() 
                             if w.status == WorkflowStatus.RUNNING)
            self.heartbeat(f"workflows [active={active_count}]")
            
            # Auto-save state every 10 seconds
            self.store.save_workflows(self.engine.active_workflows)
            await asyncio.sleep(10.0)

    async def handle_action_completed(self, event: Event) -> None:
        correlation_id = event.correlation_id
        if not correlation_id:
            return

        if not event.payload.get("success", True):
            await self.handle_action_failed(event)
            return

        await self.engine.handle_action_result(
            correlation_id, 
            success=True, 
            output=event.payload.get("output", "")
        )

    async def handle_action_denied(self, event: Event) -> None:
        correlation_id = event.correlation_id
        if not correlation_id:
            return

        workflow_id = correlation_id.split("_")[0]
        if workflow_id not in self.engine.active_workflows:
            return

        reason = event.payload.get("reason", "Action denied by operator")
        self.logger.info("workflow_step_denied", extra={"correlation_id": correlation_id, "reason": reason})
        # Gating denial cleanly stops workflow without retries
        await self.engine.handle_action_result(
            correlation_id,
            success=False,
            output="",
            error=f"Confirmation denied: {reason}",
        )

    async def handle_interrupted(self, event: Event) -> None:
        """User interrupt: cancel all running workflows and pending retries at the step boundary."""
        for workflow_id, task in list(self._retry_tasks.items()):
            if not task.done():
                task.cancel()
        self._retry_tasks.clear()

        for workflow_id, workflow in list(self.engine.active_workflows.items()):
            if workflow.status in (WorkflowStatus.RUNNING, WorkflowStatus.RECOVERING, WorkflowStatus.WAITING_CONFIRMATION):
                self.logger.info("workflow_interrupted_by_user", extra={"workflow_id": workflow_id})
                await self.engine.cancel_workflow(workflow_id, reason="User interrupted")

    async def _execute_retry_after_backoff(self, workflow, step, backoff: float) -> None:
        try:
            await asyncio.sleep(backoff)
            if workflow.status != WorkflowStatus.CANCELLED:
                await self.engine._execute_next_step(workflow)
        except asyncio.CancelledError:
            self.logger.info("workflow_retry_cancelled", extra={"workflow_id": workflow.id, "step_id": step.id})
            raise
        except Exception as e:
            self.logger.error("workflow_retry_execution_failed", exc_info=True, extra={"workflow_id": workflow.id, "step_id": step.id})
            raise
        finally:
            self._retry_tasks.pop(workflow.id, None)

    async def handle_action_failed(self, event: Event) -> None:
        correlation_id = event.correlation_id
        if not correlation_id:
            return

        workflow_id = correlation_id.split("_")[0]
        if workflow_id not in self.engine.active_workflows:
            return

        workflow = self.engine.active_workflows[workflow_id]
        step = next((s for s in workflow.steps if s.id == correlation_id), None)
        
        if not step:
            return

        step.error = event.payload.get("error", "Action failed")
        
        # Check if we can recover/retry based on idempotency and retry cap
        if self.recovery.evaluate_failure(workflow, step):
            workflow.status = WorkflowStatus.RECOVERING
            self.recovery.prepare_retry(step)
            backoff = self.recovery.get_backoff_delay(step)
            self.logger.info("workflow_step_retry", extra={"step_id": step.id, "intent": step.intent, "retry_count": step.retry_count, "backoff": backoff})
            # Non-blocking retry backoff to prevent stalling the EventBus dispatcher
            retry_task = asyncio.create_task(
                self._execute_retry_after_backoff(workflow, step, backoff),
                name=f"retry-{workflow.id}-{step.id}",
            )

            def _on_retry_done(t: asyncio.Task) -> None:
                if not t.cancelled():
                    exc = t.exception()
                    if exc is not None:
                        self.logger.error("workflow_retry_task_error", exc_info=exc, extra={"task_name": t.get_name()})

            retry_task.add_done_callback(_on_retry_done)
            self._retry_tasks[workflow.id] = retry_task
        else:
            # Fatal failure for this workflow
            await self.engine.handle_action_result(
                correlation_id, 
                success=False, 
                output="", 
                error=step.error
            )
