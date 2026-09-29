# VERIFY: Does AecProcessor.cleanup() Actually Exist?

## Skills Active
Ponytail — active. ECC — active.

The diff shown only adds `await self.aec_processor.cleanup()` to the
worker's `finally` block — it does NOT show `AecProcessor` gaining a
`cleanup()` method itself. `TtsOutputProcessor.cleanup()` already existed
from earlier work, but nothing shown defines one on `AecProcessor`.

## Required
1. Confirm: does `AecProcessor` currently have a `cleanup()` method? Show
   its exact current source. If it doesn't exist, this new call will raise
   `AttributeError` the next time the worker shuts down or restarts —
   which would ironically crash the shutdown path meant to fix the leak.
2. If missing, add it now: it must cancel `_feeder_task` (the actual
   asyncio task doing the leaking, per the earlier "dangling tasks"
   warning — confirm the exact attribute name matches what's really used,
   don't assume `_feeder_task` if the real name differs) and unsubscribe
   any event bus handlers `AecProcessor` registered, mirroring
   `TtsOutputProcessor.cleanup()`'s pattern.
3. Show the full diff for this addition.
4. Re-run full pytest, confirm 112 still passes.
5. Then do a real test: trigger at least one supervisor restart (or the
   idle-timeout path if you keep it for a quick check) and confirm no
   AttributeError appears and no dangling-task warning appears afterward.

Once confirmed, the user's hardware idle-timeout test is good to go.