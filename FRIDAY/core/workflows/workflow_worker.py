import asyncio
from ..workers.base_worker import BaseWorker
from ..events.bus import EventBus
from ..events.event_types import EventType
from ..events.models import Event
from .workflow_engine import WorkflowEngine
from .recovery import WorkflowRecovery
from .store import WorkflowStore
from .state import WorkflowStatus, WorkflowGoal


class WorkflowWorker(BaseWorker):
    """Integrates workflow management into the global event system."""

    def __init__(self, event_bus: EventBus, store: WorkflowStore | None = None):
        super().__init__("workflow_worker", event_bus)
        self.engine = WorkflowEngine(event_bus)
        self.recovery = WorkflowRecovery()
        self.store = store or WorkflowStore()
        self._retry_tasks: dict[str, asyncio.Task] = {}
        self._startup_recovery_done = False
        self._recovered_workflow_ids: set[str] = set()
        
        # Load any existing workflows from store on startup
        self.engine.active_workflows = self.store.load_workflows()

        self.event_bus.subscribe(EventType.ACTION_COMPLETED, self.handle_action_completed)
        self.event_bus.subscribe(EventType.ACTION_FAILED, self.handle_action_failed)
        self.event_bus.subscribe(EventType.ACTION_DENIED, self.handle_action_denied)
        self.event_bus.subscribe(EventType.ACTION_CONFIRMATION_REQUIRED, self.handle_confirmation_required)
        self.event_bus.subscribe(EventType.ACTION_STARTED, self.handle_action_started)
        self.event_bus.subscribe(EventType.ACTION_GRAPH_STARTED, self.handle_workflow_request)
        self.event_bus.subscribe(EventType.CONVERSATION_INTERRUPTED, self.handle_interrupted)

    async def run(self) -> None:
        await super().run()

    async def handle_workflow_request(self, event: Event) -> None:
        goal = event.payload.get("goal", "unnamed workflow")
        steps = event.payload.get("steps", [])
        if not steps:
            return
            
        workflow_id = await self.engine.create_workflow(
            goal,
            steps,
            correlation_id=event.correlation_id,
        )
        self.logger.info("workflow_initiated", extra={"workflow_id": workflow_id, "goal": goal})
        await self.engine.start_workflow(workflow_id)

    async def work(self) -> None:
        if not self._startup_recovery_done:
            await self.resume_persisted_workflows()
        while not self.should_stop:
            # Heartbeat with active workflow count
            active_count = sum(1 for w in self.engine.active_workflows.values() 
                             if w.status == WorkflowStatus.RUNNING)
            self.heartbeat(f"workflows [active={active_count}]")
            
            # Auto-save state every 10 seconds
            self.store.save_workflows(self.engine.active_workflows)
            await asyncio.sleep(10.0)

    async def resume_persisted_workflows(self) -> None:
        """Resume persisted workflows without guessing about unsafe actions.

        PENDING steps are safe to dispatch.  A RUNNING/RECOVERING step is
        only replayed when its intent is in the read-only idempotent allowlist.
        The persisted model has no dispatch/acknowledgement record, so a
        non-idempotent in-flight step is failed rather than replayed.
        """
        if self._startup_recovery_done:
            return
        self._startup_recovery_done = True

        for workflow in list(self.engine.active_workflows.values()):
            if workflow.id in self._recovered_workflow_ids:
                continue
            if workflow.status not in (WorkflowStatus.RUNNING, WorkflowStatus.RECOVERING):
                continue

            self._recovered_workflow_ids.add(workflow.id)
            await self._resume_persisted_workflow(workflow)

    async def _resume_persisted_workflow(self, workflow: WorkflowGoal) -> None:
        self.logger.info(
            "workflow_recovery_started",
            extra={"workflow_id": workflow.id, "status": workflow.status.value},
        )

        waiting_steps = [
            step for step in workflow.steps
            if step.status == WorkflowStatus.WAITING_CONFIRMATION
        ]
        if waiting_steps:
            # Confirmation futures are process-local.  Preserve the operator
            # gate and do not issue a replacement action request on restart.
            workflow.status = WorkflowStatus.WAITING_CONFIRMATION
            self.logger.info(
                "workflow_recovery_waiting_confirmation",
                extra={
                    "workflow_id": workflow.id,
                    "step_id": waiting_steps[0].id,
                },
            )
            return

        in_flight = [
            step for step in workflow.steps
            if step.status in (WorkflowStatus.RUNNING, WorkflowStatus.RECOVERING)
        ]
        failed_steps = [
            step for step in workflow.steps
            if step.status == WorkflowStatus.FAILED
        ]
        if failed_steps and in_flight:
            await self.engine.fail_workflow_for_recovery(
                workflow,
                "Restart recovery found both failed and in-flight steps; persisted state cannot prove a safe continuation.",
                step=in_flight[0],
            )
            return
        if failed_steps:
            if workflow.status != WorkflowStatus.RECOVERING or len(failed_steps) > 1:
                await self.engine.fail_workflow_for_recovery(
                    workflow,
                    "Restart recovery found a failed step without a durable retry state; refusing to guess whether replay is safe.",
                    step=failed_steps[0],
                )
                return
            failed_step = failed_steps[0]
            if not self.recovery.evaluate_failure(workflow, failed_step):
                await self.engine.fail_workflow_for_recovery(
                    workflow,
                    (
                        f"Recovery refused to retry failed step '{failed_step.intent}': "
                        "the persisted failure is not safely retryable."
                    ),
                    step=failed_step,
                )
                return
            self.recovery.prepare_retry(failed_step)
            self.engine._requested_action_step_ids.discard(failed_step.id)
            self.logger.info(
                "workflow_recovery_retrying_failed_step",
                extra={
                    "workflow_id": workflow.id,
                    "step_id": failed_step.id,
                    "intent": failed_step.intent,
                    "retry_count": failed_step.retry_count,
                },
            )

        if len(in_flight) > 1:
            await self.engine.fail_workflow_for_recovery(
                workflow,
                "Restart recovery found multiple in-flight steps; persisted state cannot prove execution order safely.",
            )
            return

        if in_flight:
            step = in_flight[0]
            if not self.recovery.is_idempotent(step.intent):
                await self.engine.fail_workflow_for_recovery(
                    workflow,
                    (
                        f"Recovery refused to replay in-flight step '{step.intent}': "
                        "persisted state cannot prove the action did not already run; "
                        "non-idempotent replay is unsafe."
                    ),
                    step=step,
                )
                return
            if (
                workflow.status == WorkflowStatus.RUNNING
                and step.retry_count == 0
                and self.recovery.max_retries <= 0
            ):
                await self.engine.fail_workflow_for_recovery(
                    workflow,
                    (
                        f"Recovery refused to replay in-flight step '{step.intent}': "
                        f"retry limit ({self.recovery.max_retries}) does not allow a replay."
                    ),
                    step=step,
                )
                return

            # A step in RECOVERING already consumed its retry budget before
            # the restart.  A RUNNING first attempt needs one retry budget
            # allocation for the safe replay.
            if workflow.status == WorkflowStatus.RUNNING and step.retry_count == 0:
                self.recovery.prepare_retry(step)
            else:
                step.status = WorkflowStatus.PENDING
                step.error = None
                step.result = None
            self.logger.info(
                "workflow_recovery_replaying_idempotent_step",
                extra={
                    "workflow_id": workflow.id,
                    "step_id": step.id,
                    "intent": step.intent,
                    "retry_count": step.retry_count,
                },
            )

        pending = next(
            (step for step in workflow.steps if step.status == WorkflowStatus.PENDING),
            None,
        )
        if pending is None and all(
            step.status == WorkflowStatus.COMPLETED for step in workflow.steps
        ):
            # Let the engine emit the normal completion events without
            # touching any completed step.
            await self.engine._execute_next_step(workflow)
            return

        if workflow.status == WorkflowStatus.RECOVERING and pending is not None:
            if not self.recovery.is_idempotent(pending.intent):
                await self.engine.fail_workflow_for_recovery(
                    workflow,
                    (
                        f"Recovery refused to resume pending recovery step '{pending.intent}': "
                        "the persisted recovery state cannot prove that replay is safe."
                    ),
                    step=pending,
                )
                return

        workflow.status = WorkflowStatus.RUNNING
        await self.engine._execute_next_step(workflow)
        self.logger.info(
            "workflow_recovery_resumed",
            extra={"workflow_id": workflow.id, "step_id": pending.id if pending else None},
        )

    async def handle_confirmation_required(self, event: Event) -> None:
        correlation_id = event.correlation_id
        if not correlation_id:
            return
        workflow_id = correlation_id.rsplit("_", 1)[0]
        workflow = self.engine.active_workflows.get(workflow_id)
        if not workflow:
            return
        step = next((s for s in workflow.steps if s.id == correlation_id), None)
        if step and step.status == WorkflowStatus.RUNNING:
            step.status = WorkflowStatus.WAITING_CONFIRMATION
            workflow.status = WorkflowStatus.WAITING_CONFIRMATION

    async def handle_action_started(self, event: Event) -> None:
        correlation_id = event.correlation_id
        if not correlation_id:
            return
        workflow_id = correlation_id.rsplit("_", 1)[0]
        workflow = self.engine.active_workflows.get(workflow_id)
        if not workflow:
            return
        step = next((s for s in workflow.steps if s.id == correlation_id), None)
        if step and step.status == WorkflowStatus.WAITING_CONFIRMATION:
            step.status = WorkflowStatus.RUNNING
            workflow.status = WorkflowStatus.RUNNING

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

        workflow_id = correlation_id.rsplit("_", 1)[0]
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

        workflow_id = correlation_id.rsplit("_", 1)[0]
        if workflow_id not in self.engine.active_workflows:
            return

        workflow = self.engine.active_workflows[workflow_id]
        step = next((s for s in workflow.steps if s.id == correlation_id), None)
        
        if not step:
            return

        # A duplicate failure for a step whose retry has already been
        # prepared must not schedule a second retry or publish a second
        # ACTION_REQUESTED event.
        if step.status != WorkflowStatus.RUNNING:
            # Preserve the existing event contract for a failure that arrives
            # before the initial ACTION_STARTED event.  Once recovery has
            # prepared a retry, the step is pending under RECOVERING and a
            # duplicate failure must be ignored.
            if step.status == WorkflowStatus.PENDING and workflow.status == WorkflowStatus.PENDING:
                step.status = WorkflowStatus.RUNNING
            else:
                return

        step.error = event.payload.get("error", "Action failed")
        
        # Check if we can recover/retry based on idempotency and retry cap
        if self.recovery.evaluate_failure(workflow, step):
            workflow.status = WorkflowStatus.RECOVERING
            # The failed request may already be recorded as published.  A
            # retry is a new attempt for the same step id and must be allowed
            # to publish exactly one replacement request.
            self.engine._requested_action_step_ids.discard(step.id)
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
