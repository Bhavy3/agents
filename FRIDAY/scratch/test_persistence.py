import asyncio
import os
import json
from core.events.bus import EventBus
from core.workflows.workflow_worker import WorkflowWorker
from core.workflows.state import WorkflowStatus

async def test_persistence_cycle():
    bus = EventBus()
    await bus.start()
    
    # 1. Create a worker and a workflow
    worker1 = WorkflowWorker(bus)
    steps = [{"intent": "step_1", "parameters": {}}, {"intent": "step_2", "parameters": {}}]
    wid = await worker1.engine.create_workflow("persistence test", steps)
    
    # 2. Advance to first step
    await worker1.engine.start_workflow(wid)
    print(f"Workflow {wid} started. Status: {worker1.engine.active_workflows[wid].status}")
    
    # 3. Save state (happens automatically in work(), but we'll force it)
    worker1.store.save_workflows(worker1.engine.active_workflows)
    print("State saved to disk.")
    
    # 4. Simulate crash/restart by creating a new worker
    print("Simulating restart...")
    bus2 = EventBus()
    worker2 = WorkflowWorker(bus2)
    
    # 5. Verify it loaded the workflow
    if wid in worker2.engine.active_workflows:
        loaded = worker2.engine.active_workflows[wid]
        print(f"Success! Workflow {wid} reloaded.")
        print(f"Goal: {loaded.goal}")
        print(f"Steps: {len(loaded.steps)}")
        print(f"Status: {loaded.status}")
    else:
        print("Failure: Workflow not found after reload.")

if __name__ == "__main__":
    asyncio.run(test_persistence_cycle())
