# FRIDAY Events

Core event types live in `core/events/event_types.py`.

Important Phase 1 events:

- `SYSTEM_READY`
- `USER_TEXT_RECEIVED`
- `INTENT_DETECTED`
- `COMMAND_EXECUTED`
- `RESPONSE_READY`
- `WORKER_FAILED`
- `WORKER_RESTARTED`
- `CRITICAL_WORKER_FAILURE`
- `SYSTEM_SHUTDOWN_REQUESTED`
- `DEADLOCK_WARNING`
- `MEMORY_WARNING`
- `MALFORMED_EVENT_DROPPED`
- `TASK_AUDIT_WARNING`
- `RUNTIME_SNAPSHOT`
- `BACKPRESSURE_APPLIED`

The event bus treats publication as a trust boundary. Malformed objects are rejected before queueing, stale events are dropped safely, handler timeouts are enforced, and metrics record processed, failed, and dropped events.
