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
