# Phase 1.6 Runtime Validation & Operational Hardening

Before audio, Ollama, desktop control, or persistent memory, FRIDAY must survive long runtime sessions.

## Required Checks

- Event flooding does not crash the event bus.
- Worker crashes trigger supervised restarts.
- Restart loops do not kill the runtime.
- Malformed events are dropped and logged.
- Invalid commands are blocked by default.
- Shutdown drains queued events and flushes logs.
- Runtime metrics track queue depth, processed events, failed events, dropped events, restart count, and processing time.
- Terminal `status` shows worker state, queue depth, restart count, uptime, and event metrics.
- Plugin registration and execution failures are isolated from the runtime.

## Long Session Test

After Python 3.12+ is installed:

```powershell
cd FRIDAY
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
python -m unittest discover tests
python main.py
```

Let the runtime operate for multiple hours before enabling real automation.

## 8-Hour Runtime Validation

```powershell
python main.py --validate-runtime --duration-seconds 28800
```

This mode does not enable real automation. It only simulates commands, malformed events, queue pressure, and worker crashes.

## Phase 1.7 Burn-In Checks

- Memory monitoring tracks traced allocations, queue depth, object count, and growth trends.
- Deadlock detection emits `DEADLOCK_WARNING` when queues stall without processing progress.
- Async task auditing warns on abnormal task growth.
- Runtime snapshots include workers, queues, metrics, task counts, memory usage, event rates, and anomalies.
- Failure replay stores recent critical events before worker isolation or restart.
- Backpressure drops low-priority events when queue utilization is high while preserving critical events.
- Malformed events emit `MALFORMED_EVENT_DROPPED` and never enter the event queue.
- Repeated worker failure emits `CRITICAL_WORKER_FAILURE` and quarantines the unstable worker without killing the runtime.
- Worker transitions are logged as `worker_state_transition` with `from_state`, `to_state`, `reason`, `worker`, and `restart_count`.
- Supervisor loop lifetime is tested so worker failure does not terminate supervision before restart or quarantine completes.
