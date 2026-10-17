TASK: Full read-only audit of FRIDAY covering ALL 10 Omega objectives equally. Do NOT edit, create, delete, move, stage, commit, checkout, reset, or stash anything inside the repo. Write the report to C:\Users\bhavy\Desktop\friday_audit\REPORT.md (outside the repo). Scratch scripts and captured logs go in C:\Users\bhavy\Desktop\friday_audit\scratch.

EVIDENCE RULE (every line of the report)
Each claim needs: the exact command, the raw output (trimmed to relevant lines), and one status:
  VERIFIED = real run, real components, output shown
  FAILED = real run that shows the defect, output shown
  MOCK-ONLY = the only evidence involves a mock or fake object
  UNKNOWN = could not check (state the exact blocker)
Do not assume any Omega is unbuilt. "NOT BUILT" is allowed only if a grep over core/, interfaces/, scripts/ and tests/ for the item's keywords finds no implementation, and the grep output is shown.
Never write "should", "appears", or "expected" in place of output.

PART 0: SPEC FIRST
Search AGENTS.md, docs/, FRIDAY_MASTER_LOOP_PROMPT.md, INSTALL_PLAN.md and any file containing "Omega" or "Ω". For each of the 10 objectives, quote its written definition and acceptance criteria. If an objective has no written spec, say so and use this fallback, labelled as a guess:
  Ω.1 Realtime Presence: always-listening, instant-feeling interaction
  Ω.2 Latency: fast time to first token and total response
  Ω.3 VAD interruption: user can interrupt speech reliably without early cut-off
  Ω.4 Memory: explicit-trigger save and relevant recall
  Ω.5 Autonomous workflows: multi-step tasks with safety gates
  Ω.6 Emotional presence: tone modulation affecting wording only
  Ω.7 Survival and escalation: recovery plus 3B to 7B model swap
  Ω.8 Device ecosystem: coordination with other devices
  Ω.9 Adaptive routing: choose model by complexity and latency budget
  Ω.10 Illusion of Life: natural, alive-feeling behavior
Test each objective against its written spec, not against my fallback.

PART 1: INVENTORY
1. git rev-parse HEAD ; git status --porcelain ; git log --oneline -20
2. File counts for core/, tests/, scripts/, scratch/, root. List root-level leftovers.
3. .\.venv\Scripts\python.exe -m compileall -q core interfaces main.py ; every failure.
4. Import every .py under core/ in a subprocess; list each ImportError.
5. AST scan: duplicated definitions in one file; modules under core/ imported by nothing.
6. AST static scan of core/ with FILE:LINE and quoted line: except blocks containing only pass or print; print() outside scripts; bare except; EventTypes published but never subscribed, and the reverse.
7. Mock detection: grep -rn "Mock\|MagicMock\|AsyncMock\|patch(" scripts/ scratch/ tests/. List every script or test that fakes a router, LLM, TTS, STT, search, or audio. Results that depend on them cannot be VERIFIED.

PART 2: TESTS
8. .\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider ; summary plus every failing test with its assertion.
9. For each failure: stale test, environment problem, or real bug, with the proving line quoted.

PART 3: THE 10 OBJECTIVES (identical treatment for each)
Prerequisite: GET http://127.0.0.1:8080/health. If down, start it as in start_friday_local.bat and record that.
For EACH of Ω.1 to Ω.10, produce this block:
  a. Spec (quoted from Part 0)
  b. Implementing files (grep output)
  c. Its tests, and which use mocks
  d. One REAL end-to-end check with real components and no mocks, with command and raw output
  e. Status (VERIFIED / FAILED / MOCK-ONLY / UNKNOWN / NOT BUILT with grep proof)
  f. If not VERIFIED: root cause with FILE:LINE and quoted code, and the smallest fix described in words
Suggested live checks:
  Ω.1 and Ω.3 need a microphone and speaker: run main.py with audio, speak 3 prompts, interrupt one long answer, and paste STT transcripts, SPEECH_STARTED and TTS_PLAYBACK_CANCELLED timestamps, and the safety-net warning count. If hardware is unavailable, mark UNKNOWN and print the exact steps for me to perform and what to paste back.
  Ω.2: 5 real prompts through the real orchestrator; paste time to first token and total time for each.
  Ω.4: use a COPY of the memory DB in the audit folder; save a fact, recall it, ask an unrelated question (fact must not appear), ask a related one (fact must appear).
  Ω.5: one real workflow ("first search for the capital of France, then remember it") against the DB copy; paste plan, step results, final text.
  Ω.6: 6 utterances (confident, cautious, curious, warm, neutral, factual); paste the exact system text sent to the model and the reply; report any contradiction between tone and personality blocks.
  Ω.7: trigger the 3B to 7B swap and back 3 times; paste model_manager logs, swap times, nvidia-smi before and after, and any orphan llama-server process.
  Ω.8: exercise whatever the spec defines (read the code first); paste the real interaction.
  Ω.9: 10 real prompts across simple, medium and complex; paste routing_decision and routing_executed, the model used, and any decision that contradicts its own rule.
  Ω.10: test the behaviors the spec names; paste real transcripts.

PART 4: CROSS-CUTTING
10. Web answers, real, no mock: ask "What's the weather right now?", "Who won the most recent FIFA World Cup?", "What is the capital of Australia?", "What time is it?", "Search for the latest Python release". For each: router raw output, parameters reaching ACTION_REQUESTED, search results (saved to the audit folder), spoken answer, and whether every number, URL and place name in the answer appears in the results.
11. Stop llama-server, send one prompt, record what the user sees and the logs, then restart it.
12. Send 3 prompts 1 second apart; report lost turns, duplicates, exceptions.
13. Idle 10 minutes; report worker states and ERROR lines.
14. Count ERROR and WARNING lines in data/logs/friday.log by event name; list the top 10.

PART 5: REPORT (REPORT.md)
 A. Table: Ω.1 to Ω.10 | Status | Main reason | Evidence file and line.
 B. Per objective: what it should do, what it does, root cause (FILE:LINE, quoted), smallest fix in words (no code).
 C. All defects ranked: (1) wrong or invented answers, (2) lost or silent turns, (3) crashes, (4) wrong log levels or prints, (5) dead code. Each with FILE:LINE and impact.
 D. Earlier "verified" claims that are MOCK-ONLY or contradicted.
 E. What was not checked, and why.
 F. Counts only: VERIFIED, FAILED, MOCK-ONLY, UNKNOWN, NOT BUILT out of 10. No percentage not computed from these counts.

RULES
- Fix nothing. Suggest nothing that changes the repo.
- A step that hangs over 5 minutes: record it and continue.
- At the end run git status --porcelain and paste it. It must match step 1 (only AGENTS.md modified, plus the stray file).
- In chat print only the Part 5A table and the path to REPORT.md.
## Current Project Handoff — 2026-10-17

The earlier read-only audit instruction above described a prior task. The user later granted standing approval for text-mode Omega completion on branch `omega-finish`, including milestone commits, focused regression tests, and updates to this handoff. Do not infer approval to edit voice/audio code from that approval.

### Current state

- M0 checkpoint: `3ffe8f2 chore: checkpoint existing FRIDAY work before Omega completion`.
- M1 text-mode fixes: `015cb4a fix: bound workflow context and log text mode failures`.
- M2 adds a text-mode evidence harness at `scripts/verify_text_mode.py`, a memory DB path override (`FRIDAY_MEMORY_DB_PATH`), normalization for planner `input` aliases on `search_web` and `remember`, and a temporal grounding check for time-sensitive queries. M2 verification passed (300 passed, 3 warnings in an isolated copy) and commit `cc56c90 fix: verify text mode workflows and web grounding` is saved.
- Use only `.venv\Scripts\python.exe`. Keep `PYTHONDONTWRITEBYTECODE=1` and use pytest `-p no:cacheprovider`; run the full suite from an isolated copy excluding `.git`, `.venv`, caches, model files, and database files.
- Keep evidence and scratch files under `C:\Users\bhavy\Desktop\friday_audit`. The harness uses `friday_memory_audit_copy.db` and `text_mode_ledger.jsonl`; do not point it at or mutate the project memory database.
- `FRIDAY_AUDIO_ENABLED=false` is required for text-mode checks. Do not modify `core/audio/*`, VAD, TTS, AEC, or Pipecat files without fresh user authorization.
- The original written Omega acceptance document has not been supplied or located in the repository. Do not invent numeric acceptance criteria or create `docs/OMEGA.md` until the user supplies that source text.
- Recovery requires the user to stop and restart their own local llama-server. Never terminate a user-owned server process as part of the harness.

### Verification commands

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
.\.venv\Scripts\python.exe -B -m pytest tests -q -p no:cacheprovider
.\.venv\Scripts\python.exe -B scripts\verify_text_mode.py --mode local
.\.venv\Scripts\python.exe -B scripts\verify_text_mode.py --mode live --idle-seconds 0
.\.venv\Scripts\python.exe -B scripts\verify_text_mode.py --mode workflow
.\.venv\Scripts\python.exe -B scripts\verify_text_mode.py --mode idle --idle-seconds 600
.\.venv\Scripts\python.exe -B scripts\verify_text_mode.py --mode recovery
```

### Voice re-enable checklist

1. Obtain explicit authorization before changing `core/audio/*` or enabling audio.
2. Review and resolve audio exception handlers and diagnostics in the authorized scope.
3. With microphone and speaker available, run three prompts and one long-answer interruption; capture transcripts, `SPEECH_STARTED`, `TTS_PLAYBACK_CANCELLED`, and safety-net warning timestamps.
4. Run audio/VAD/TTS/AEC tests and confirm shutdown leaves no audio worker or playback process running.
