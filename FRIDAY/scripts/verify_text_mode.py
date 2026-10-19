"""Run FRIDAY text-mode checks and append raw evidence outside the repository.

Use ``--mode local`` for memory persistence and local router/tone decisions that
do not require llama-server. Use ``--mode live`` after starting the real server
for application prompts. This harness never enables audio and never writes to
the repository memory database.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sys
import time
import urllib.error
import urllib.request
import uuid
from collections import defaultdict
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_AUDIT_DIR = Path(r"C:\Users\bhavy\Desktop\friday_audit")
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MEMORY_DB = REPO_ROOT / "data/memory/friday_memory.db"
sys.path.insert(0, str(REPO_ROOT))
LIVE_EVENT_TYPES = {
    "ACTION_COMPLETED",
    "ACTION_CONFIRMATION_REQUIRED",
    "ACTION_DENIED",
    "ACTION_FAILED",
    "ACTION_GRAPH_COMPLETED",
    "ACTION_GRAPH_FAILED",
    "ACTION_REQUESTED",
    "ASSISTANT_RESPONSE_COMPLETED",
    "ASSISTANT_RESPONSE_PARTIAL",
    "CONVERSATION_TURN_ENDED",
    "LLM_FAILURE",
    "LLM_REQUEST_SENT",
    "LLM_RESPONSE_RECEIVED",
    "MEMORY_CONTEXT_READY",
    "MEMORY_QUERY_REQUEST",
    "MEMORY_QUERY_RESULT",
    "MEMORY_WRITE_COMPLETED",
    "MEMORY_WRITE_REQUEST",
    "MEMORY_DENIED",
    "MEMORY_FAILURE",
    "RESPONSE_READY",
    "ROUTE_REQUESTED",
    "STREAM_CHUNK",
    "STREAM_COMPLETED",
    "STREAM_FAILED",
}


class EvidenceLedger:
    def __init__(self, path: Path, command: str):
        self.path = path
        self.command = command

    def record(self, name: str, kind: str, output: Any, exit_code: int = 0) -> None:
        entry = {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "name": name,
            "command": self.command,
            "exit_code": exit_code,
            "kind": kind,
            "raw_output": output,
        }
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
        print(json.dumps(entry, ensure_ascii=True, default=str))


def health_check(base_url: str, timeout: float = 3.0) -> dict[str, Any]:
    url = base_url.rstrip("/") + "/health"
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            return {"url": url, "status": response.status, "body": body}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {"url": url, "error": repr(exc)}


def events_for_correlation(events: list[dict[str, Any]], correlation_id: str) -> list[dict[str, Any]]:
    """Keep evidence scoped to the prompt turn that produced it."""
    return [item for item in events if item.get("correlation_id") == correlation_id]


def prepare_memory_copy(audit_dir: Path) -> Path:
    audit_dir.mkdir(parents=True, exist_ok=True)
    target = audit_dir / "friday_memory_audit_copy.db"
    source = DEFAULT_MEMORY_DB
    if source.is_file():
        shutil.copy2(source, target)
        print(f"Copied memory database: {source} -> {target}")
    else:
        print(f"No source memory database at {source}; a fresh audit database will be created at {target}")
    return target


async def wait_event(future: asyncio.Future, timeout: float = 8.0) -> Any:
    return await asyncio.wait_for(future, timeout=timeout)


async def run_local(audit_dir: Path, ledger: EvidenceLedger) -> None:
    """Exercise the real SQLite memory worker and pure local decision code."""
    from core.events.bus import EventBus
    from core.events.event_types import EventType
    from core.events.models import Event
    from core.memory.memory_store import MemoryStore
    from core.memory.memory_worker import MemoryWorker
    from core.router.adaptive_router import AdaptiveRouter
    from core.cognition.cognitive_state import CognitiveStateEngine

    db_path = prepare_memory_copy(audit_dir)
    bus = EventBus()
    await bus.start()
    worker = MemoryWorker(bus, db_path=str(db_path))
    await worker.start()
    await asyncio.sleep(0.1)

    async def memory_request(event_type: EventType, payload: dict, correlation_id: str) -> dict:
        result = asyncio.get_running_loop().create_future()

        async def capture(event: Event) -> None:
            if event.correlation_id == correlation_id and not result.done():
                result.set_result(event.payload)

        response_type = (
            EventType.MEMORY_WRITE_COMPLETED
            if event_type == EventType.MEMORY_WRITE_REQUEST
            else EventType.MEMORY_QUERY_RESULT
        )
        bus.subscribe(response_type, capture)
        await bus.publish(Event.create(event_type, payload, "verify_text_mode", correlation_id))
        return await wait_event(result)

    save = await memory_request(
        EventType.MEMORY_WRITE_REQUEST,
        {
            "content": "Audit-only fact: preferred editor is Vim.",
            "type": "approved_fact",
            "source": "explicit_user_request",
            "explicit_user_approved": True,
        },
        "audit-memory-save",
    )
    related = await memory_request(
        EventType.MEMORY_QUERY_REQUEST,
        {"query": "Which editor do I prefer?", "limit": 5},
        "audit-memory-related",
    )
    unrelated = await memory_request(
        EventType.MEMORY_QUERY_REQUEST,
        {"query": "volcanoes in Iceland", "limit": 5},
        "audit-memory-unrelated",
    )
    await worker.stop()
    await bus.stop()

    restarted = MemoryStore(str(db_path))
    persisted = await restarted.query()
    output = {
        "db_copy": str(db_path),
        "save": save,
        "related_results": related.get("results", []),
        "unrelated_results": unrelated.get("results", []),
        "records_after_worker_restart_count": len(persisted),
        "audit_fact_persisted": any("preferred editor is Vim" in record.content for record in persisted),
    }
    ledger.record("memory_copy_save_restart_recall", "live-local-components", output)

    router = AdaptiveRouter()
    prompts = [
        "What is 2 + 2?",
        "Summarize this short paragraph in one sentence.",
        "Compare three database indexing strategies and explain their trade-offs.",
    ]
    decisions = []
    for prompt in prompts:
        model, reason = await router.decide_model(prompt)
        decisions.append({"prompt": prompt, "decision": model, "reason": reason})
    ledger.record("adaptive_router_local_decisions", "live-local-component", decisions)

    tone_engine = CognitiveStateEngine(None)
    utterances = {
        "confident": "I am certain this is the right choice.",
        "cautious": "I might be wrong; could you check this carefully?",
        "curious": "I wonder how this works; can we explore it?",
        "warm": "I feel overwhelmed and could use some support.",
        "neutral": "Please explain how a database index works.",
        "factual": "Give me the date and numeric measurements only.",
    }
    tones = []
    for label, utterance in utterances.items():
        await tone_engine.update_tone(utterance)
        tones.append({"label": label, "detected": tone_engine.current_tone, "context": tone_engine.get_tone_context()})
    ledger.record("tone_detection_local", "live-local-component", tones)


async def run_live(audit_dir: Path, ledger: EvidenceLedger, *, idle_seconds: int) -> None:
    """Drive the real FridayApp with audio disabled and the copied memory DB."""
    from core.config.settings import load_settings
    from core.events.event_types import EventType
    from core.events.models import Event

    db_path = prepare_memory_copy(audit_dir)
    os.environ["FRIDAY_AUDIO_ENABLED"] = "false"
    os.environ["FRIDAY_MEMORY_DB_PATH"] = str(db_path)
    os.environ["FRIDAY_LOG_DIR"] = str(audit_dir / "logs")

    settings = replace(load_settings(), root_dir=audit_dir, audio_enabled=False)
    from core.app import FridayApp

    health = health_check(settings.ollama_base_url)
    ledger.record("llama_server_health", "live", health, 0 if health.get("status") == 200 else 1)
    if health.get("status") != 200:
        ledger.record(
            "live_mode_blocked",
            "blocked",
            "Start llama-server with start_friday_local.bat, then rerun this command. No live prompts were sent.",
            2,
        )
        return

    app = FridayApp(settings=settings)
    captured: list[dict[str, Any]] = []
    captured_prompts: list[dict[str, Any]] = []

    def instrument_real_stream(client) -> None:
        original_stream_generate = client.stream_generate

        async def capture_real_stream(prompt: str, *args, **kwargs):
            captured_prompts.append({"time": time.perf_counter(), "prompt": prompt})
            async for chunk in original_stream_generate(prompt, *args, **kwargs):
                yield chunk

        # Observe the exact prompt while delegating unchanged to the real client/server.
        client.stream_generate = capture_real_stream

    instrument_real_stream(app.ollama_client)

    async def capture(event) -> None:
        if event.event_type.value in LIVE_EVENT_TYPES:
            captured.append({
                "time": time.perf_counter(),
                "event": event.event_type.value,
                "correlation_id": event.correlation_id,
                "payload": event.payload,
            })

    app.event_bus.subscribe_all(capture)
    await app.start()
    await asyncio.sleep(1.0)  # Let supervised workers register event handlers.

    async def send_prompt(name: str, text: str, timeout: float = 90.0) -> None:
        correlation_id = f"verify-{name}-{uuid.uuid4().hex[:8]}"
        start = time.perf_counter()
        before = len(captured)
        prompt_before = len(captured_prompts)
        await app.event_bus.publish(Event.create(
            EventType.USER_TEXT_RECEIVED,
            {"text": text},
            "verify_text_mode",
            correlation_id,
        ))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            await asyncio.sleep(0.1)
            batch = captured[before:]
            related = events_for_correlation(batch, correlation_id)
            if any(item["event"] == "ASSISTANT_RESPONSE_COMPLETED" for item in related):
                break
            if any(item["event"] in {"ACTION_GRAPH_COMPLETED", "ACTION_GRAPH_FAILED"} for item in related):
                break
            if any(item["event"] == "RESPONSE_READY" for item in related):
                # Let queued completion / workflow events arrive before snapshot.
                await asyncio.sleep(0.5)
                break
        batch = captured[before:]
        related = events_for_correlation(batch, correlation_id)
        stream_times = [item["time"] for item in related if item["event"] == "STREAM_CHUNK"]
        output = {
            "prompt": text,
            "elapsed_seconds": round(time.perf_counter() - start, 3),
            "time_to_first_stream_chunk_seconds": round(stream_times[0] - start, 3) if stream_times else None,
            "correlation_id": correlation_id,
            "exact_model_prompts": [item["prompt"] for item in captured_prompts[prompt_before:]],
            "outcome": (
                "workflow_failed" if any(item["event"] == "ACTION_GRAPH_FAILED" for item in related)
                else "completed" if any(item["event"] == "ASSISTANT_RESPONSE_COMPLETED" for item in related)
                else "no_completion_event"
            ),
            "events": related,
        }
        ledger.record(name, "live-real-app", output, 0 if output["outcome"] != "no_completion_event" else 1)

    try:
        web_prompts = [
            "What's the weather right now?",
            "Who won the most recent FIFA World Cup?",
            "What is the capital of Australia?",
            "What time is it?",
            "Search for the latest Python release.",
        ]
        for index, prompt in enumerate(web_prompts, 1):
            await send_prompt(f"web-{index}", prompt)

        await send_prompt("workflow-search-remember", "First search for the capital of France, then remember it.", timeout=180.0)

        await send_prompt("memory-save", "Remember that the audit color code is cobalt 4317.")
        await asyncio.sleep(1.0)
        await send_prompt("memory-unrelated", "How does a bicycle chain transfer motion?")

        await app.stop()
        app = FridayApp(settings=settings)
        instrument_real_stream(app.ollama_client)
        app.event_bus.subscribe_all(capture)
        await app.start()
        await asyncio.sleep(1.0)
        await send_prompt("memory-recall-after-app-restart", "What was the audit color code?")

        tone_prompts = [
            "I am certain this is the right answer.",
            "I may be mistaken; please check this carefully.",
            "I wonder why this happens; can we explore it?",
            "I feel discouraged and could use encouragement.",
            "Please explain how a database index works.",
            "Give the exact date and numeric measurements only.",
        ]
        for index, prompt in enumerate(tone_prompts, 1):
            await send_prompt(f"tone-{index}", prompt)

        routing_prompts = [
            "What is 2 + 2?",
            "Name the capital of Australia.",
            "Give one short definition of a database index.",
            "Summarize the difference between HTTP and HTTPS.",
            "Explain how a B-tree index supports range queries.",
            "Compare three database indexing strategies and their trade-offs.",
            "Design a migration plan from a monolith to services, including rollback and observability.",
            "Analyze this concurrency bug and propose a minimal fix with tests.",
            "Plan a safe workflow that searches for a fact, verifies it, and stores it only after confirmation.",
            "Explain the limits of this estimate and derive the result step by step: 17.5% of 2480, then compare it with 430.",
        ]
        for index, prompt in enumerate(routing_prompts, 1):
            await send_prompt(f"routing-{index}", prompt)

        burst = ["What is 2 + 2?", "Explain why leaves change color.", "Name one capital city in Europe."]
        for index, prompt in enumerate(burst, 1):
            await send_prompt(f"burst-{index}", prompt)
            if index < len(burst):
                await asyncio.sleep(1.0)

        gate_before = len(captured)
        denied_path = audit_dir / "denied-write-must-not-exist.txt"
        gate_goal = f"verify-gated-write-{uuid.uuid4().hex[:8]}"
        await app.event_bus.publish(Event.create(
            EventType.ACTION_GRAPH_STARTED,
            {
                "goal": "Verify that a denied write does not execute.",
                "steps": [{
                    "intent": "write_text_file",
                    "parameters": {"file_path": str(denied_path), "content": "This write must be denied."},
                }],
            },
            "verify_text_mode",
            gate_goal,
        ))
        gate_deadline = time.monotonic() + 15.0
        confirmation = None
        while time.monotonic() < gate_deadline and confirmation is None:
            await asyncio.sleep(0.05)
            confirmation = next(
                (item for item in captured[gate_before:] if item["event"] == "ACTION_CONFIRMATION_REQUIRED"),
                None,
            )
        if confirmation:
            app.tool_worker.confirmations.resolve_confirmation(confirmation["correlation_id"], False)
            deny_deadline = time.monotonic() + 10.0
            while time.monotonic() < deny_deadline:
                await asyncio.sleep(0.05)
                if any(item["event"] == "ACTION_DENIED" for item in captured[gate_before:]):
                    break
        gate_events = captured[gate_before:]
        ledger.record("gated_write_denial", "live-real-app", {
            "events": gate_events,
            "denied_target_exists": denied_path.exists(),
            "confirmation_observed": confirmation is not None,
        }, 0 if confirmation and not denied_path.exists() else 1)

        if idle_seconds > 0:
            idle_start = time.monotonic()
            await asyncio.sleep(idle_seconds)
            worker_states = [
                {"name": worker.name, "state": getattr(worker, "state", None), "task_done": worker.task.done() if getattr(worker, "task", None) else None}
                for worker in app.supervisor.workers
            ]
            log_path = audit_dir / "data" / "logs" / "friday.log"
            error_lines = []
            if log_path.is_file():
                error_lines = [line.rstrip("\r\n") for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines() if '"level":"ERROR"' in line or '"level": "ERROR"' in line]
            ledger.record("idle_soak", "live-real-app", {
                "elapsed_seconds": round(time.monotonic() - idle_start, 2),
                "worker_states": worker_states,
                "error_lines": error_lines,
            })
        log_path = audit_dir / "data" / "logs" / "friday.log"
        routing_lines = []
        if log_path.is_file():
            routing_lines = [
                line.rstrip("\r\n")
                for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines()
                if "routing_decision:" in line or "routing_executed:" in line
            ]
        ledger.record("routing_decisions_and_execution_logs", "live-real-app", routing_lines)
    finally:
        await app.stop()


async def run_recovery(audit_dir: Path, ledger: EvidenceLedger, *, recovery_wait_seconds: int) -> None:
    """Probe a user-stopped llama-server, then wait for the user to restart it."""
    from core.config.settings import load_settings
    from core.events.event_types import EventType
    from core.events.models import Event

    db_path = prepare_memory_copy(audit_dir)
    os.environ["FRIDAY_AUDIO_ENABLED"] = "false"
    os.environ["FRIDAY_MEMORY_DB_PATH"] = str(db_path)
    settings = replace(load_settings(), root_dir=audit_dir, audio_enabled=False)
    before = health_check(settings.ollama_base_url)
    ledger.record("recovery_health_before", "live", before, 0 if before.get("status") != 200 else 1)
    if before.get("status") == 200:
        ledger.record("recovery_blocked", "blocked", "Stop llama-server first; this harness never kills a user-owned server.", 2)
        return

    from core.app import FridayApp

    app = FridayApp(settings=settings)
    captured: list[dict[str, Any]] = []

    async def capture(event) -> None:
        captured.append({
            "time": time.perf_counter(),
            "event": event.event_type.value,
            "correlation_id": event.correlation_id,
            "payload": event.payload,
        })

    app.event_bus.subscribe_all(capture)
    await app.start()
    await asyncio.sleep(1.0)

    async def send_probe(name: str, prompt: str, timeout: float = 25.0) -> list[dict[str, Any]]:
        correlation_id = f"verify-{name}-{uuid.uuid4().hex[:8]}"
        before_index = len(captured)
        await app.event_bus.publish(Event.create(
            EventType.USER_TEXT_RECEIVED,
            {"text": prompt},
            "verify_text_mode",
            correlation_id,
        ))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            await asyncio.sleep(0.1)
            if any(item["correlation_id"] == correlation_id and item["event"] in {
                "ASSISTANT_RESPONSE_COMPLETED", "RESPONSE_READY", "LLM_FAILURE", "STREAM_FAILED", "STREAM_TIMEOUT"
            } for item in captured[before_index:]):
                break
        events = captured[before_index:]
        ledger.record(name, "live-real-app", {"prompt": prompt, "correlation_id": correlation_id, "events": events})
        return events

    try:
        await send_probe("llama_stopped_prompt", "Reply with the word offline-check.")
        ledger.record("waiting_for_user_to_restart_llama", "blocked", {
            "instruction": "Start the local server again while this harness waits.",
            "wait_seconds": recovery_wait_seconds,
        })
        deadline = time.monotonic() + recovery_wait_seconds
        while time.monotonic() < deadline:
            await asyncio.sleep(2.0)
            after = health_check(settings.ollama_base_url, timeout=1.0)
            if after.get("status") == 200:
                ledger.record("recovery_health_after", "live", after)
                await send_probe("llama_recovered_prompt", "Reply with the word recovered.")
                return
        ledger.record("recovery_timeout", "blocked", f"Server did not recover within {recovery_wait_seconds} seconds.", 1)
    finally:
        await app.stop()


async def run_workflow_probe(audit_dir: Path, ledger: EvidenceLedger) -> None:
    """Run the real planner → search → remember workflow against the local server."""
    from core.config.settings import load_settings
    from core.events.event_types import EventType
    from core.events.models import Event

    db_path = prepare_memory_copy(audit_dir)
    os.environ["FRIDAY_AUDIO_ENABLED"] = "false"
    os.environ["FRIDAY_MEMORY_DB_PATH"] = str(db_path)
    settings = replace(load_settings(), root_dir=audit_dir, audio_enabled=False)
    health = health_check(settings.ollama_base_url)
    ledger.record("workflow_probe_health", "live", health, 0 if health.get("status") == 200 else 1)
    if health.get("status") != 200:
        ledger.record("workflow_probe_blocked", "blocked", "Start llama-server with start_friday_local.bat and retry.", 2)
        return

    from core.app import FridayApp

    app = FridayApp(settings=settings)
    captured: list[dict[str, Any]] = []

    async def capture(event) -> None:
        if event.event_type.value in LIVE_EVENT_TYPES:
            captured.append({
                "time": time.perf_counter(),
                "event": event.event_type.value,
                "correlation_id": event.correlation_id,
                "payload": event.payload,
            })

    app.event_bus.subscribe_all(capture)
    await app.start()
    await asyncio.sleep(1.0)
    prompt = "First search for the capital of France, then remember it."
    correlation_id = f"verify-workflow-{uuid.uuid4().hex[:8]}"
    start = time.perf_counter()
    before = len(captured)
    try:
        await app.event_bus.publish(Event.create(
            EventType.USER_TEXT_RECEIVED,
            {"text": prompt},
            "verify_text_mode",
            correlation_id,
        ))
        deadline = time.monotonic() + 120.0
        while time.monotonic() < deadline:
            await asyncio.sleep(0.1)
            batch = captured[before:]
            if any(item["event"] in {"ACTION_GRAPH_COMPLETED", "ACTION_GRAPH_FAILED"} for item in batch):
                break
        events = captured[before:]
        outcome = (
            "failed" if any(item["event"] == "ACTION_GRAPH_FAILED" for item in events)
            else "completed" if any(item["event"] == "ACTION_GRAPH_COMPLETED" for item in events)
            else "timeout"
        )
        ledger.record("real_search_then_remember_workflow", "live-real-app", {
            "prompt": prompt,
            "correlation_id": correlation_id,
            "elapsed_seconds": round(time.perf_counter() - start, 3),
            "outcome": outcome,
            "events": events,
        }, 0 if outcome == "completed" else 1)
    finally:
        await app.stop()


async def run_idle_probe(audit_dir: Path, ledger: EvidenceLedger, *, idle_seconds: int) -> None:
    """Keep the real text-only application idle and summarize worker/log state."""
    from core.config.settings import load_settings

    db_path = prepare_memory_copy(audit_dir)
    os.environ["FRIDAY_AUDIO_ENABLED"] = "false"
    os.environ["FRIDAY_MEMORY_DB_PATH"] = str(db_path)
    settings = replace(load_settings(), root_dir=audit_dir, audio_enabled=False)
    health = health_check(settings.ollama_base_url)
    ledger.record("idle_probe_health", "live", health, 0 if health.get("status") == 200 else 1)
    if health.get("status") != 200:
        ledger.record("idle_probe_blocked", "blocked", "Start llama-server with start_friday_local.bat and retry.", 2)
        return

    from core.app import FridayApp

    log_path = audit_dir / "data" / "logs" / "friday.log"
    app = FridayApp(settings=settings)
    initial_log_size = log_path.stat().st_size if log_path.is_file() else 0
    await app.start()
    await asyncio.sleep(0.1)  # Let supervised worker tasks enter their running state.
    start = time.monotonic()
    active_log_bytes = b""
    worker_states: list[dict[str, Any]] = []
    try:
        await asyncio.sleep(max(0, idle_seconds))
        if log_path.is_file():
            active_log_bytes = log_path.read_bytes()[initial_log_size:]
        worker_states = [
            {
                "name": worker.name,
                "state": worker.health.state.value,
                "alive": worker.health.alive,
                "current_task": worker.health.current_task,
                "restart_count": worker.health.restart_count,
            }
            for worker in app.supervisor.workers
        ]
    finally:
        await app.stop()

    try:
        all_log_bytes = log_path.read_bytes() if log_path.is_file() else b""
        run_log_bytes = all_log_bytes[initial_log_size:]
        all_log_lines = run_log_bytes.decode("utf-8", errors="replace").splitlines()
        shutdown_log_lines = all_log_bytes[initial_log_size + len(active_log_bytes):].decode(
            "utf-8", errors="replace"
        ).splitlines()
        counts: dict[str, int] = defaultdict(int)
        log_errors: list[str] = []
        shutdown_warnings: list[str] = []
        for line in all_log_lines:
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            level = item.get("level", "")
            if level in {"ERROR", "WARNING", "WARN"}:
                event_name = str(item.get("message") or item.get("logger") or "unknown")
                counts[f"{level}:{event_name}"] += 1
                if level == "ERROR":
                    log_errors.append(line)
        for line in shutdown_log_lines:
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if item.get("level") in {"WARNING", "WARN"}:
                shutdown_warnings.append(line)
        ledger.record("idle_soak", "live-real-app", {
            "elapsed_seconds": round(time.monotonic() - start, 2),
            "worker_states": worker_states,
            "worker_count": len(worker_states),
            "error_count": len(log_errors),
            "top_error_warning_events": sorted(counts.items(), key=lambda pair: pair[1], reverse=True)[:10],
            "error_lines": log_errors,
            "shutdown_warning_lines": shutdown_warnings,
        })
    except Exception as exc:
        ledger.record("idle_soak_summary_failed", "failed", {"exception": repr(exc)}, 1)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("local", "live", "recovery", "workflow", "idle"), default="local")
    parser.add_argument("--audit-dir", type=Path, default=DEFAULT_AUDIT_DIR)
    parser.add_argument("--idle-seconds", type=int, default=600, help="Live-mode idle soak; set 0 to skip.")
    parser.add_argument("--recovery-wait-seconds", type=int, default=300)
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    args.audit_dir.mkdir(parents=True, exist_ok=True)
    ledger = EvidenceLedger(args.audit_dir / "text_mode_ledger.jsonl", " ".join(os.sys.argv))
    os.environ["FRIDAY_AUDIO_ENABLED"] = "false"
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        if args.mode == "local":
            asyncio.run(run_local(args.audit_dir, ledger))
        elif args.mode == "recovery":
            asyncio.run(run_recovery(args.audit_dir, ledger, recovery_wait_seconds=args.recovery_wait_seconds))
        elif args.mode == "workflow":
            asyncio.run(run_workflow_probe(args.audit_dir, ledger))
        elif args.mode == "idle":
            asyncio.run(run_idle_probe(args.audit_dir, ledger, idle_seconds=args.idle_seconds))
        else:
            asyncio.run(run_live(args.audit_dir, ledger, idle_seconds=args.idle_seconds))
    except Exception as exc:
        ledger.record("harness_exception", "failed", {"exception": repr(exc)}, 1)
        raise
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
