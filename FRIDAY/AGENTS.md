# FRIDAY — Verification Pass: Executor Deletion + Memory Wiring Investigation

Ponytail active. This is VERIFICATION AND INVESTIGATION only — do not delete, wire up,
or change anything yet unless explicitly told to in a specific step below. I need solid
evidence before we decide what to do next.

## Part 1 — Justify the executor deletion (accountability check)

You reported "Executor Deletion & Cleanup: DONE — the dead core/executor/ package and
its tests were purged." I need the same level of evidence you gave for the plugin
deletion earlier:

1. Pull the actual code that was in `core/executor/` from git history (all files, not
   a summary).
2. Explain exactly what functionality it provided, and where (if anywhere) that
   functionality now lives instead — is it truly replaced by ToolWorker/ToolRegistry,
   or is this a capability that's now gone with nothing replacing it?
3. Confirm: was anything still importing from `core/executor/` at the time of deletion?
   Grep the codebase (or check pre-deletion git state) for any references. If anything
   was still importing it, explain how that was handled (updated to use the
   replacement, or would have broken).
4. List which tests were deleted alongside it and what they were asserting.

Report this plainly — if the deletion was correct, say so with evidence. If anything
here is ambiguous or you're not fully certain, say that too rather than asserting
confidence you don't have.

## Part 2 — Confirm the orchestrator lock fix actually works (not just "reported done")

You reported the `_state_lock` fix as DONE for `active_turn_id`, `active_speaker`,
`context`, and `_routing_task`. Verify this properly:

1. Show the current code for every mutation site of these four fields, confirming each
   is inside the lock.
2. Confirm the regression test that was supposed to be added (simulating concurrent
   mutation of active_speaker) actually exists, actually runs, and actually would fail
   without the lock (i.e. it's a real test, not a trivial one that passes regardless).
   If this test doesn't exist or doesn't meaningfully test the race, write it now and
   confirm it fails on a deliberately un-locked version and passes on the current code.
3. Run the full test suite and report the current total pass count.

## Part 3 — Memory wiring investigation (no changes yet, just findings)

Investigate what it would take to wire `MemoryWorker`'s `MEMORY_CONTEXT_READY` event
into the Orchestrator's conversational context:

1. Show the exact payload shape of `MEMORY_CONTEXT_READY` (what data does it actually
   contain — pinned notes, preferences, something else?).
2. Show where in `conversation.py` the LLM prompt/context gets assembled before being
   sent to `stream_reasoning()` or the classification call — this is where memory
   content would need to be injected.
3. Propose the MINIMAL change to subscribe the Orchestrator to `MEMORY_CONTEXT_READY`
   and fold relevant memory content into the context sent to the LLM. Don't implement
   yet — just describe the specific 1-2 mutation points and roughly how many lines of
   change this would realistically be, so I can judge scope before approving.
4. Flag any risk: could injecting memory content bloat the prompt significantly (recall
   our earlier latency work — context size matters), and if so, suggest how much
   memory content is reasonable to inject per turn (e.g. top N pinned items, not the
   whole database).

## Deliverable
Three clearly separated sections (Parts 1, 2, 3) with concrete evidence — actual code,
actual test results, actual payload shapes. No fixes beyond what Part 2 explicitly
requires (writing/verifying the regression test). Part 3 is a proposal for my approval,
not an implementation.