# FRIDAY Phase 1 Architecture

FRIDAY Phase 1 is infrastructure-first. The runtime is built around an async event bus, supervised workers, a hybrid router, and a dry-run command executor.

## Runtime Flow

```text
terminal input -> USER_TEXT_RECEIVED -> router -> INTENT_DETECTED -> executor -> RESPONSE_READY
```

## Phase 1.5 Stabilization

- Event dispatch drops malformed events without crashing the dispatcher.
- Worker health tracks alive state, last heartbeat, restart count, and current task.
- Command history is session-only and records command, timestamp, result, and metadata.
- Dry-run actions return simulated output and safety validation metadata.
- Shutdown cancels async tasks, drains queued events, stops supervised workers, and flushes logs.

## Phase 1.6 Operational Hardening

- Watchdog supervision detects blocked workers through heartbeat age.
- Restart-loop protection quarantines unhealthy workers before they destabilize the runtime.
- Queue protection enforces bounded queues, stale event drops, handler timeouts, and overflow accounting.
- Runtime validation mode simulates command traffic, malformed events, queue pressure, worker crashes, and memory monitoring.
- Terminal `status` renders a lightweight operational dashboard.

## Phase 1.7 Burn-In

- Operational monitoring creates periodic runtime snapshots.
- Memory and task auditors detect abnormal growth before audio workers are introduced.
- Failure replay preserves recent critical events for debugging failure chains.
- Backpressure protects the event queue from memory explosion during floods.
- Critical events bypass normal backpressure rules.
- The event bus validates event objects at the publication boundary before backpressure or queue logic.
- Thread safety remains event-loop-owned; future audio threads must hand off through event-safe queues.

Worker lifecycle states are explicit: `STARTING`, `RUNNING`, `RESTARTING`, `FAILED`, `DISABLED`, `QUARANTINED`, and `STOPPED`.

Restart lifecycle is explicit:

```text
FAILED -> RESTARTING -> STARTING -> RUNNING
FAILED -> RESTARTING -> QUARANTINED
```

Restart attempts increment before relaunch decisions. Rapid repeated failures are timestamped in a supervisor-owned restart window and quarantine the worker instead of leaving it in `FAILED`.

The supervisor coroutine is persistent for the worker lifetime. It repeatedly creates a fresh worker task, awaits exactly one run outcome, classifies the result, then either continues the supervision loop for restart or breaks after intentional stop/quarantine.

## Rules

- `main.py` only starts the runtime.
- `core/app.py` manages lifecycle.
- Workers never directly call each other.
- Plugins register capabilities dynamically.
- The executor never directly trusts LLM output.
- Recovery manager records failures and emits a single user-facing fallback per worker.
