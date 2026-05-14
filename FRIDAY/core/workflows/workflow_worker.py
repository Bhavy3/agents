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
        
        # Load any existing workflows from store on startup
        self.engine.active_workflows = self.store.load_workflows()

    async def run(self) -> None:
        self.event_bus.subscribe(EventType.ACTION_COMPLETED, self.handle_action_completed)
        self.event_bus.subscribe(EventType.ACTION_FAILED, self.handle_action_failed)
        self.event_bus.subscribe(EventType.ACTION_GRAPH_STARTED, self.handle_workflow_request)
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
            
        await self.engine.handle_action_result(
            correlation_id, 
            success=True, 
            output=event.payload.get("output", "")
        )

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
        
        # Check if we can recover/retry
        if self.recovery.evaluate_failure(workflow, step):
            workflow.status = WorkflowStatus.RECOVERING
            self.recovery.prepare_retry(step)
            # Re-trigger step after a small delay
            await asyncio.sleep(1.0)
            await self.engine._execute_next_step(workflow)
        else:
            # Fatal failure for this workflow
            await self.engine.handle_action_result(
                correlation_id, 
                success=False, 
                output="", 
                error=step.error
            )
