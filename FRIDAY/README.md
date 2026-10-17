# FRIDAY

FRIDAY is a local, event-driven AI operating system foundation for Windows desktop automation.

Phase 1 prioritizes runtime stability over intelligence:

- async event bus
- supervised workers
- hybrid router with rule-first behavior
- dry-run executor
- plugin-registered commands
- centralized structured logging
- graceful shutdown

## Run

```powershell
cd FRIDAY
python main.py
```

## Setup

Install Python 3.12+ and enable `Add Python to PATH`.

```powershell
python --version
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

`asyncio` is part of Python 3.12+ and should not be installed from PyPI.

## Initial Commands

- `open chrome`
- `open folder <path>`
- `search google for <query>`
- `help`
- `status`
- `exit`

All actions are dry-run only in Phase 1.

## Test

```powershell
python -m unittest discover tests
pytest
```

## Runtime Validation

The local llama.cpp launcher and `ModelManager` use `FRIDAY_LLAMA_NGL` as the
canonical GPU-layer setting. It defaults to `33` in both paths. Set it before
starting FRIDAY when the local GPU needs a different offload count, for example
`$env:FRIDAY_LLAMA_NGL = '12'`. The older `FRIDAY_LLAMA_GPU_LAYERS` and
`FRIDAY_LLM_GPU_LAYERS` names remain accepted as fallbacks.

```powershell
python main.py --burn-in --duration-seconds 28800
```

This runs an 8-hour validation pass with simulated commands, malformed events, queue pressure, worker crashes, metrics, and memory monitoring. The current CLI flag is `--burn-in`; `--validate-runtime` remains a hidden compatibility alias for older launch scripts.

The validation report includes uptime, restart stats, memory trends, event throughput, detected anomalies, and failure replay data.

## Text-mode verification

Use the project virtual environment and disable bytecode/cache writes when
checking the repository:

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
.\.venv\Scripts\python.exe -B -m pytest tests -q -p no:cacheprovider
.\.venv\Scripts\python.exe -B scripts\verify_text_mode.py --mode local
```

`local` uses real memory, routing, and tone components without llama-server.
For live text-only checks, start the server with `start_friday_local.bat`, then
run:

```powershell
.\.venv\Scripts\python.exe -B scripts\verify_text_mode.py --mode live --idle-seconds 0
.\.venv\Scripts\python.exe -B scripts\verify_text_mode.py --mode workflow
.\.venv\Scripts\python.exe -B scripts\verify_text_mode.py --mode idle --idle-seconds 600
```

The harness copies `data/memory/friday_memory.db` to
`C:\Users\bhavy\Desktop\friday_audit\friday_memory_audit_copy.db`, forces
text-only mode, and stores the event evidence in
`C:\Users\bhavy\Desktop\friday_audit\text_mode_ledger.jsonl`. Recovery mode
expects the operator to stop the local server first; it never terminates a
user-owned llama-server process:

```powershell
.\.venv\Scripts\python.exe -B scripts\verify_text_mode.py --mode recovery
```

## Current verification limits

- The original numeric Ω acceptance document has not been supplied, so the
  scorecard cannot yet claim conformance to its targets.
- Voice, VAD, TTS, AEC, and Pipecat source files remain locked; microphone,
  speaker, barge-in, and audio safety-net checks remain unverified.
- The local live pass uses one 3B llama-server endpoint. It does not prove
  3B↔7B model swaps or GPU-offload performance.
- External web search may fail. FRIDAY returns a safe fallback when search
  fails or an answer is not grounded in the returned results.

## Voice re-enable checklist

Keep `FRIDAY_AUDIO_ENABLED=false` for text-only work. Before enabling voice:

1. Review and explicitly authorize any changes to `core/audio/*`.
2. Resolve the remaining audio exception handlers and diagnostic prints.
3. With a microphone and speaker available, run three prompts and one long
   answer interruption; capture transcripts, `SPEECH_STARTED`,
   `TTS_PLAYBACK_CANCELLED`, and safety-net warning timestamps.
4. Run the audio/VAD/TTS/AEC tests and confirm normal shutdown leaves no audio
   worker or playback process running.

As of 2026-10-17, the full suite passed in an isolated copy: 300 passed,
3 import warnings. Raw output is stored at
`C:\Users\bhavy\Desktop\friday_audit\scratch\M2_full_suite.txt`.
