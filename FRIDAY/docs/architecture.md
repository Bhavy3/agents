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

## Local Memory

- `MemoryWorker` stores validated memory records in SQLite; generated IDs are UUID-based, and an existing record is updated only when a write supplies its explicit ID.
- Memory writes normalize and deduplicate repeated sentences. Approved facts require explicit approval; secrets, unsafe shell patterns, empty or oversized content, and secret-bearing metadata are rejected.
- The conversation path creates an approved-fact write only for explicit leading requests such as “remember that …”, “remember my …”, “don’t forget that …”, or “save this: …”. Other turns are not automatically stored.
- Retrieval uses deterministic term overlap, exact-phrase, type, confidence, approval, and recency scoring. Recency uses a 30-day half-life bounded to a 0.35 minimum multiplier.
- Each text turn requests bounded recall through the event bus. Only validated, relevant content is injected into the router's chat instructions, with a 1,200-character cap; record metadata is not included.
- Conversation summaries are deterministic extracts of supplied text and pass through the same validation and SQLite persistence path. Conversation turns are not automatically stored.

## Web Search

- `search_web` uses the keyless `ddgs` text-search library, returns at most five title/snippet pairs, and bounds the result text to 1,500 characters. `open_url` remains the separate browser-opening action.
- Search requests and results use the existing `ACTION_REQUESTED` and `ACTION_COMPLETED` events. The orchestrator streams a short answer using the bounded results as explicitly untrusted reference data; search-result text is never routed back through the tool classifier.
- Slow searches emit a spoken progress acknowledgment after one second. Search failures are logged and produce a concise spoken fallback.

## Rules

- `main.py` only starts the runtime.
- `core/app.py` manages lifecycle.
- Workers never directly call each other.
- Plugins register capabilities dynamically.
- The executor never directly trusts LLM output.
- Recovery manager records failures and emits a single user-facing fallback per worker.
