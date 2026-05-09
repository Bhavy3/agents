# Thread Safety Review

FRIDAY Phase 1.7 remains single-event-loop first.

## Current Shared State

- `EventBus` queue access is owned by the asyncio event loop.
- `RuntimeMetrics` is updated from runtime tasks on the same event loop.
- `WorkerHealth` is updated by supervised worker tasks on the same event loop.
- `CommandHistory` is session-only and updated by the executor on the event loop.
- Python logging handlers are thread-safe and use rotating file handlers.

## Current Thread Boundary

The terminal interface uses `asyncio.to_thread(input, ...)` only to avoid blocking the event loop. It returns text back into the event loop before publishing events.

## Audio Phase Rule

Future audio/STT/TTS integrations must not mutate runtime state directly from external threads. They must use event-loop-safe handoff mechanisms such as:

- `asyncio.run_coroutine_threadsafe`
- `loop.call_soon_threadsafe`
- dedicated async queues

No worker should share mutable state with another worker outside the event bus.
