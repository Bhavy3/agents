Phase 11.0 — Autonomous Workflow Intelligence
Goal

Turn FRIDAY from:

Reactive Assistant

into:

Goal-Oriented Runtime

WITHOUT creating:

uncontrolled autonomy
recursive agents
self-prompt loops
runaway planners

This phase adds:

bounded planning
workflow execution
recovery logic
multi-step reasoning
safe autonomous sequencing
What Phase 11 Adds
1. Workflow Engine

Create:

core/workflows/workflow_engine.py

Purpose:
Execute bounded multi-step tasks safely.

Example:

Workflow(
    goal="debug supervisor issue",
    steps=[
        "open_logs",
        "search_failures",
        "summarize_root_cause",
    ]
)
2. Planner (Bounded)

Create:

core/workflows/planner.py

STRICT LIMITS:

max 5 steps
no recursion
no self-replanning loops
no autonomous internet exploration

Planner only:

decomposes tasks
selects tools
tracks progress
3. Workflow State Machine

Create:

core/workflows/state.py

States:

PENDING
RUNNING
WAITING_CONFIRMATION
FAILED
RECOVERING
COMPLETED
CANCELLED

All typed.
All deterministic.

4. Recovery Runtime

Create:

core/workflows/recovery.py

Purpose:
Recover from:

failed tool calls
timeout
partial workflow completion

Recovery rules:

retry max 2 times
fallback tool allowed
otherwise fail safely
5. Tool Sequencing

FRIDAY can now chain:

Vision → OCR → Memory → Tool → Summary

Example:

"Read this error on my screen and fix it."

Pipeline:

capture screen
OCR extract
summarize error
search logs/files
suggest fix
6. Human Approval Layer

ANY dangerous workflow step:

pauses execution
requests confirmation
resumes only after approval

No silent escalation.

7. Long Task Continuity

Workflow survives:

interruptions
conversation switches
temporary LLM failures

State stored in:

core/workflows/store.py

Bounded history only.

8. Workflow Dashboard

Display:

active_workflow=debug_runtime
step=3/5
status=recovering
tool=filesystem
retries=1
9. Prompt Planning Layer

Create:

core/workflows/prompt_planner.py

Purpose:
Generate:

compact plans
structured execution goals
bounded reasoning context

NO chain-of-thought exposure.

10. Multi-Modal Workflowing

FRIDAY can combine:

speech
vision
memory
tools
reasoning

inside one supervised workflow.

HARD RULES
NEVER:
create recursive agents
create self-improving systems
allow autonomous shell execution
allow unrestricted browsing
allow autonomous persistence expansion
allow hidden planning
FILE LIMITS

Each file:

<180 lines

No giant orchestrators.

REQUIRED TESTS

Create:

tests/test_workflows.py

Validate:

bounded planning
workflow cancellation
retry recovery
confirmation gates
interruption safety
persistence recovery
timeout handling
SUCCESS CONDITION

FRIDAY should now:

complete multi-step tasks
recover from failures
maintain workflow continuity
coordinate tools intelligently
remain safe and supervised

WITHOUT becoming an uncontrolled autonomous agent.