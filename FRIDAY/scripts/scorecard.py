"""FRIDAY progress scorecard.

Runs every measurement needed to judge progress on the Omega plan and prints a
single JSON document.  Exit code is 0 unless ``--strict`` is passed.

Metrics
-------
plan_validity    BoundedPlanner success rate over a fixed goal set.
ttft_ms          Time to first streamed content token from the local model.
events_dropped   EventBus deliveries lost under a publish flood.
sandbox_escapes  Filesystem confinement matrix failures.
tests            pytest collected test count.

Usage
-----
    ./.venv/Scripts/python.exe -B scripts/scorecard.py
    ./.venv/Scripts/python.exe -B scripts/scorecard.py --skip-llm
    ./.venv/Scripts/python.exe -B scripts/scorecard.py --out scratch/scorecard.json

The LLM-backed metrics need llama-server.  If it is not answering, this script
starts it (same defaults as start_llm.bat) and stops it again afterwards.  It
never stops a server it did not start.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

FRIDAY_ROOT = Path(__file__).resolve().parents[1]
SCRATCH_DIR = FRIDAY_ROOT / "scratch"

# Import order matters: probes expect to be imported with the project on sys.path.
sys.path.insert(0, str(FRIDAY_ROOT))
sys.path.insert(0, str(SCRATCH_DIR))

DEFAULT_BASE_URL = os.getenv("FRIDAY_LLM_BASE_URL", "http://127.0.0.1:8080")
DEFAULT_SERVER_BIN = os.getenv("FRIDAY_LLAMA_SERVER", r"C:\AI\llama.cpp\llama-server.exe")
DEFAULT_MODEL_PATH = os.getenv(
    "FRIDAY_LLM_MODEL_PATH", r"C:\AI\models\qwen2.5-3b-instruct-q5_k_m.gguf"
)

# Gate thresholds from the remediation plan.
TARGETS = {
    "plan_validity": 0.90,
    "ttft_ms": 500.0,
    "events_dropped_ratio": 0.01,
    "sandbox_escapes": 0,
    "tests_collected": 451,
}

PLAN_TRIALS = int(os.getenv("SCORECARD_PLAN_TRIALS", "2"))
FLOOD_EVENTS = int(os.getenv("SCORECARD_FLOOD_EVENTS", "1200"))


# --------------------------------------------------------------------------- #
# LLM server lifecycle
# --------------------------------------------------------------------------- #
def _health(url: str, timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(f"{url.rstrip('/')}/health", timeout=timeout) as response:
            return response.status == 200
    except (urllib.error.URLError, OSError, ValueError):
        return False


def _start_llama_server(base_url: str) -> subprocess.Popen | None:
    """Start llama-server for llm metrics. Caller owns the returned process."""
    binary = Path(DEFAULT_SERVER_BIN)
    model = Path(DEFAULT_MODEL_PATH)
    if not binary.is_file() or not model.is_file():
        return None

    from urllib.parse import urlparse

    parsed = urlparse(base_url)
    host = parsed.hostname or "127.0.0.1"
    port = str(parsed.port or 8080)

    SCRATCH_DIR.mkdir(parents=True, exist_ok=True)
    log_path = SCRATCH_DIR / "scorecard_llama.log"
    log = open(log_path, "w", encoding="utf-8", errors="replace")
    try:
        process = subprocess.Popen(
            [
                str(binary),
                "-m", str(model),
                "-c", "4096",
                "--host", host,
                "--port", port,
            ],
            stdout=log,
            stderr=subprocess.STDOUT,
            cwd=str(FRIDAY_ROOT),
        )
    except OSError:
        log.close()
        return None

    deadline = time.perf_counter() + 120.0
    while time.perf_counter() < deadline:
        if _health(base_url):
            return process
        if process.poll() is not None:
            return None
        time.sleep(0.5)

    process.terminate()
    return None


def _stop_process(process: subprocess.Popen | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        process.kill()


# --------------------------------------------------------------------------- #
# Metric: plan validity
# --------------------------------------------------------------------------- #
def collect_plan_validity(base_url: str) -> dict:
    """Reuse the planner probe so the scorecard measures the shipped code path."""
    import asyncio

    import test_planner_json as probe

    probe.BASE_URL = base_url

    async def _run() -> dict:
        valid = 0
        total = 0
        stages: dict[str, int] = {}
        failures: list[dict] = []
        for goal in probe.GOALS:
            for _ in range(PLAN_TRIALS):
                result = await probe.run_current_planner(goal)
                total += 1
                if result["ok"]:
                    valid += 1
                else:
                    stage = str(result.get("stage", "unknown"))
                    stages[stage] = stages.get(stage, 0) + 1
                    failures.append(
                        {
                            "goal": goal,
                            "stage": stage,
                            "detail": str(result.get("detail"))[:160],
                        }
                    )
        return {"valid": valid, "total": total, "stages": stages, "failures": failures}

    raw = asyncio.run(_run())
    rate = raw["valid"] / raw["total"] if raw["total"] else 0.0
    return {
        "value": round(rate, 4),
        "target": TARGETS["plan_validity"],
        "pass": rate >= TARGETS["plan_validity"],
        "samples": raw["total"],
        "valid": raw["valid"],
        "failure_stages": raw["stages"],
        "failures": raw["failures"][:10],
    }


# --------------------------------------------------------------------------- #
# Metric: time to first streamed token
# --------------------------------------------------------------------------- #
def collect_ttft(base_url: str, samples: int = 3) -> dict:
    import asyncio

    import httpx

    async def _one() -> float | None:
        payload = {
            "messages": [{"role": "user", "content": "Say hello in exactly five words."}],
            "max_tokens": 24,
            "temperature": 0.0,
            "stream": True,
            "model": "local",
        }
        started = time.perf_counter()
        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream(
                "POST", f"{base_url.rstrip('/')}/v1/chat/completions", json=payload
            ) as response:
                if response.status_code != 200:
                    return None
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if not data or data == "[DONE]":
                        continue
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    delta = (chunk.get("choices") or [{}])[0].get("delta") or {}
                    if delta.get("content"):
                        return (time.perf_counter() - started) * 1000.0
        return None

    async def _run() -> list[float]:
        values: list[float] = []
        for _ in range(samples):
            value = await _one()
            if value is not None:
                values.append(value)
        return values

    values = asyncio.run(_run())
    if not values:
        return {
            "value": None,
            "target": TARGETS["ttft_ms"],
            "pass": False,
            "note": "no streamed content token received",
            "samples": samples,
        }
    values.sort()
    median = values[len(values) // 2]
    return {
        "value": round(median, 1),
        "target": TARGETS["ttft_ms"],
        "pass": median <= TARGETS["ttft_ms"],
        "samples": len(values),
        "min_ms": round(values[0], 1),
        "max_ms": round(values[-1], 1),
    }


# --------------------------------------------------------------------------- #
# Metric: events dropped under flood
# --------------------------------------------------------------------------- #
def collect_events_dropped(total: int = FLOOD_EVENTS) -> dict:
    import asyncio

    from core.events.bus import EventBus
    from core.events.event_types import EventType
    from core.events.models import Event

    async def _run() -> dict:
        bus = EventBus()  # production defaults: queue 1000, real watermarks
        delivered = 0

        async def slow_handler(event: Event) -> None:
            nonlocal delivered
            delivered += 1
            await asyncio.sleep(0.002)

        # Dropped events are logged at ERROR; keep the scorecard's own output clean.
        import logging

        bus_logger = logging.getLogger("friday.events.bus")
        previous_level = bus_logger.level
        bus_logger.setLevel(logging.CRITICAL)

        bus.subscribe(EventType.RUNTIME_SNAPSHOT, slow_handler)
        await bus.start()
        try:
            started = time.perf_counter()
            for index in range(total):
                await bus.publish(
                    Event.create(
                        EventType.RUNTIME_SNAPSHOT, {"seq": index}, "scorecard"
                    )
                )
            publish_seconds = time.perf_counter() - started

            # Stop as soon as delivery goes quiet instead of waiting out a fixed
            # deadline: dropped events will never arrive.
            deadline = time.perf_counter() + 30.0
            last_delivered = -1
            quiet_since = time.perf_counter()
            while delivered < total and time.perf_counter() < deadline:
                await asyncio.sleep(0.02)
                if delivered != last_delivered:
                    last_delivered = delivered
                    quiet_since = time.perf_counter()
                elif time.perf_counter() - quiet_since > 1.0:
                    break
        finally:
            await bus.stop()
            bus_logger.setLevel(previous_level)

        return {
            "published": total,
            "delivered": delivered,
            "dropped": max(0, total - delivered),
            "publish_seconds": round(publish_seconds, 3),
            "queue_size": bus.max_queue_size,
        }

    raw = asyncio.run(_run())
    ratio = raw["dropped"] / raw["published"] if raw["published"] else 0.0
    return {
        "value": round(ratio, 4),
        "target": TARGETS["events_dropped_ratio"],
        "pass": ratio <= TARGETS["events_dropped_ratio"],
        **raw,
    }


# --------------------------------------------------------------------------- #
# Metric: sandbox escapes
# --------------------------------------------------------------------------- #
def collect_sandbox_escapes() -> dict:
    """Run the confinement matrix probe and read its structured result rows."""
    import test_confinement_matrix as probe

    import asyncio

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        asyncio.run(probe.main())

    rows = list(probe.ROWS)
    failures = [{"check": label, "detail": detail} for label, ok, detail in rows if not ok]
    return {
        "value": len(failures),
        "target": TARGETS["sandbox_escapes"],
        "pass": len(failures) <= TARGETS["sandbox_escapes"],
        "checks": len(rows),
        "failures": failures,
    }


# --------------------------------------------------------------------------- #
# Metric: test count
# --------------------------------------------------------------------------- #
def collect_tests(run_suite: bool = False) -> dict:
    command = [sys.executable, "-B", "-m", "pytest", "tests", "-q", "-p", "no:cacheprovider"]
    if not run_suite:
        command.append("--collect-only")

    completed = subprocess.run(
        command,
        cwd=str(FRIDAY_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=600,
    )
    output = (completed.stdout or "") + (completed.stderr or "")

    collected = None
    passed = None
    for line in output.splitlines():
        stripped = line.strip()
        # collect mode: "451 tests collected in 0.52s"
        if collected is None and "collected" in stripped:
            for token in stripped.split():
                if token.isdigit():
                    collected = int(token)
                    break
        # run mode: "451 passed in 93.28s"
        if passed is None and " passed" in stripped:
            parts = stripped.split()
            for index, token in enumerate(parts):
                if token == "passed" and index and parts[index - 1].isdigit():
                    passed = int(parts[index - 1])
                    break
    if collected is None:
        collected = passed

    value = passed if run_suite and passed is not None else collected
    return {
        "value": value,
        "target": TARGETS["tests_collected"],
        "pass": bool(value and value >= TARGETS["tests_collected"]),
        "mode": "run" if run_suite else "collect",
        "collected": collected,
        "passed": passed,
        "returncode": completed.returncode,
        "tail": output.strip().splitlines()[-1] if output.strip() else "",
    }


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def _safe(name: str, fn, *args, **kwargs) -> dict:
    started = time.perf_counter()
    try:
        result = fn(*args, **kwargs)
        result["seconds"] = round(time.perf_counter() - started, 2)
        return result
    except Exception as exc:  # keep the scorecard running when one metric breaks
        return {
            "value": None,
            "pass": False,
            "error": f"{type(exc).__name__}: {exc}",
            "seconds": round(time.perf_counter() - started, 2),
        }


def _git_commit() -> str | None:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(FRIDAY_ROOT),
            capture_output=True,
            text=True,
            timeout=10,
        )
        return (completed.stdout or "").strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description="FRIDAY Omega progress scorecard.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="llama-server base URL.")
    parser.add_argument("--skip-llm", action="store_true", help="Skip plan validity and TTFT.")
    parser.add_argument("--no-start-llm", action="store_true", help="Never start llama-server.")
    parser.add_argument("--run-tests", action="store_true", help="Run the suite instead of collecting.")
    parser.add_argument("--out", default=None, help="Also write the JSON report to this path.")
    parser.add_argument("--strict", action="store_true", help="Exit 1 when any gate fails.")
    args = parser.parse_args()

    os.chdir(FRIDAY_ROOT)

    server: subprocess.Popen | None = None
    llm_state = {"base_url": args.base_url, "available": False, "auto_started": False}

    if not args.skip_llm:
        llm_state["available"] = _health(args.base_url)
        if not llm_state["available"] and not args.no_start_llm:
            server = _start_llama_server(args.base_url)
            llm_state["auto_started"] = server is not None
            llm_state["available"] = server is not None

    try:
        metrics: dict[str, dict] = {}

        if llm_state["available"]:
            metrics["plan_validity"] = _safe("plan_validity", collect_plan_validity, args.base_url)
            metrics["ttft_ms"] = _safe("ttft_ms", collect_ttft, args.base_url)
        else:
            reason = "llm endpoint unavailable"
            metrics["plan_validity"] = {"value": None, "pass": False, "skipped": reason}
            metrics["ttft_ms"] = {"value": None, "pass": False, "skipped": reason}

        metrics["events_dropped"] = _safe("events_dropped", collect_events_dropped)
        metrics["sandbox_escapes"] = _safe("sandbox_escapes", collect_sandbox_escapes)
        metrics["tests"] = _safe("tests", collect_tests, args.run_tests)
    finally:
        _stop_process(server)

    evaluated = [m for m in metrics.values() if not m.get("skipped")]
    passed = sum(1 for m in evaluated if m.get("pass"))
    report = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "project": "FRIDAY",
        "git_commit": _git_commit(),
        "python": sys.version.split()[0],
        "llm": llm_state,
        "targets": TARGETS,
        "metrics": metrics,
        "summary": {
            "gates_passed": passed,
            "gates_evaluated": len(evaluated),
            "gates_skipped": len(metrics) - len(evaluated),
            "all_green": bool(evaluated) and passed == len(evaluated),
        },
    }

    text = json.dumps(report, indent=2)
    print(text)

    if args.out:
        out_path = Path(args.out)
        if not out_path.is_absolute():
            out_path = FRIDAY_ROOT / out_path
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text + "\n", encoding="utf-8")

    if args.strict and not report["summary"]["all_green"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
