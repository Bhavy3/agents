"""Voice Re-Enable Staging Item 5: 6+ Minute Idle Test.

Verifies:
- Pre-idle baseline (< 2s)
- 6 min 30 sec (390s) idle period with all runtime workers active
- Zero worker timeouts, deadlocks, or exception handlers
- Post-idle query responsiveness (< 2s)
- State integrity across all subsystems
Logs all events and metrics to data/logs/idle_test.log.
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path
import httpx

# Ensure root is on path
root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))

os.environ["FRIDAY_AUDIO_ENABLED"] = "false"

from core.app import FridayApp
from core.events.bus import EventBus
from core.events.event_types import EventType
from core.events.models import Event
from core.config.settings import load_settings
from core.llm.local_llm_client import create_llm_client
from core.cognition.tone_detector import detect_tone
from core.router.complexity_detector import detect_query_complexity

sys.stdout.reconfigure(encoding="utf-8")


async def run_item5_idle_suite():
    log_dir = root / "data" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    idle_log_path = log_dir / "idle_test.log"
    log_file = open(idle_log_path, "w", encoding="utf-8")

    def log(msg: str):
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        formatted = f"[{ts}] {msg}"
        print(formatted)
        log_file.write(formatted + "\n")
        log_file.flush()

    log("=" * 60)
    log("ITEM 5: 6+ MINUTE IDLE TEST STARTING")
    log("=" * 60)

    settings = load_settings()

    # -------------------------------------------------------------------------
    # STEP 1: PRE-IDLE SYSTEM STATE (Baseline Snapshot)
    # -------------------------------------------------------------------------
    log("\n" + "=" * 60)
    log("STEP 1: PRE-IDLE SYSTEM STATE (BASELINE SNAPSHOT)")
    log("=" * 60)

    pre_bus = EventBus()
    await pre_bus.start()
    pre_client = create_llm_client(
        settings.ollama_base_url,
        settings.ollama_model,
        30.0,
        2,
        settings.llm_provider,
    )

    t0 = time.perf_counter()
    pre_resp, pre_metrics = await pre_client.generate("hello", max_tokens=5)
    pre_elapsed = time.perf_counter() - t0

    pre_text = pre_resp.strip() if pre_resp else ""
    client_active = (not pre_client._client.is_closed) if pre_client._client else True
    bus_started = pre_bus._running

    log(f"Pre-idle baseline: {pre_elapsed:.2f}s response | response='{pre_text}'")
    log(f"Client state: active={client_active}")
    log(f"Bus state: started={bus_started}")

    await pre_client.aclose()
    await pre_bus.stop()

    # -------------------------------------------------------------------------
    # STEP 2: IDLE PERIOD (6 min 30 sec / 390 seconds)
    # -------------------------------------------------------------------------
    log("\n" + "=" * 60)
    log("STEP 2: STARTING FRIDAY APP IN TEXT-ONLY MODE (IDLE DURATION: 390s)")
    log("=" * 60)

    app = FridayApp(settings)
    await app.start()
    log("FRIDAY App started successfully with full worker supervisor.")
    log(f"Active workers: {[w.name for w in app.supervisor.workers]}")

    errors_recorded = []

    async def on_error_event(e: Event):
        if e.event_type in (
            EventType.ERROR_OCCURRED,
            EventType.WORKER_FAILED,
            EventType.CRITICAL_WORKER_FAILURE,
            EventType.DEADLOCK_WARNING,
        ):
            errors_recorded.append(e)
            log(f"⚠ ERROR EVENT DURING IDLE: {e.event_type.value} -> {e.payload}")

    app.event_bus.subscribe(EventType.ERROR_OCCURRED, on_error_event)
    app.event_bus.subscribe(EventType.WORKER_FAILED, on_error_event)
    app.event_bus.subscribe(EventType.CRITICAL_WORKER_FAILURE, on_error_event)
    app.event_bus.subscribe(EventType.DEADLOCK_WARNING, on_error_event)

    idle_target_seconds = 390.0  # 6 minutes 30 seconds
    idle_start_time = time.perf_counter()
    check_interval = 30.0  # Log heartbeat status every 30s

    log(f"Entering idle period for {idle_target_seconds}s (6m 30s)...")
    while True:
        elapsed = time.perf_counter() - idle_start_time
        if elapsed >= idle_target_seconds:
            break
        await asyncio.sleep(min(check_interval, idle_target_seconds - elapsed))
        cur_elapsed = time.perf_counter() - idle_start_time
        workers_alive = sum(1 for w in app.supervisor.workers if not w.should_stop)
        log(
            f"Idle progress: {cur_elapsed:.1f}s / {idle_target_seconds:.0f}s | "
            f"Workers alive: {workers_alive}/{len(app.supervisor.workers)} | "
            f"Errors: {len(errors_recorded)}"
        )

    total_idle_elapsed = time.perf_counter() - idle_start_time
    log(f"✓ Idle period complete: {total_idle_elapsed:.2f}s elapsed (Target: >= 390s).")
    log(f"Errors detected during idle: {len(errors_recorded)}")

    # -------------------------------------------------------------------------
    # STEP 3: POST-IDLE QUERY (Verify Responsiveness)
    # -------------------------------------------------------------------------
    log("\n" + "=" * 60)
    log("STEP 3: POST-IDLE QUERY (VERIFY RESPONSIVENESS)")
    log("=" * 60)

    url = f"{settings.ollama_base_url}/completion"
    payload = {"prompt": "What is your name?", "n_predict": 20}

    t_post = time.perf_counter()
    async with httpx.AsyncClient(timeout=10.0) as http_client:
        post_resp = await http_client.post(url, json=payload)
        post_data = post_resp.json()
    post_elapsed = time.perf_counter() - t_post

    post_content = post_data.get("content", "").strip()[:100]
    log(f"Post-idle response time: {post_elapsed:.2f}s (Target: < 2.0s)")
    log(f"Response: '{post_content}'")

    # -------------------------------------------------------------------------
    # STEP 4: STATE INTEGRITY CHECK (Verify No Corruption)
    # -------------------------------------------------------------------------
    log("\n" + "=" * 60)
    log("STEP 4: STATE INTEGRITY CHECK (VERIFY NO CORRUPTION)")
    log("=" * 60)

    health = await app.ollama_client.health_check()
    log(f"LLM client health: {health}")

    bus_active = getattr(app.event_bus, "_running", False)
    q_depth = app.event_bus.queue_depth if hasattr(app.event_bus, "queue_depth") else 0
    log(f"Event bus state: started={bus_active}, queue_depth={q_depth}")

    tone = detect_tone("thanks for waiting")
    log(f"Tone detector works: tone={tone}")

    complexity = detect_query_complexity("explain quantum mechanics")
    log(f"Complexity detector works: complexity={complexity}")

    # Conversation turn test
    response_received = asyncio.Event()
    received_text = ""

    async def on_turn_response(e: Event):
        nonlocal received_text
        if e.event_type == EventType.RESPONSE_READY:
            received_text = e.payload.get("text", "")
            response_received.set()

    app.event_bus.subscribe(EventType.RESPONSE_READY, on_turn_response)

    await app.event_bus.publish(
        Event.create(
            EventType.USER_TEXT_RECEIVED,
            {"text": "Hello, are you still there?"},
            source="test_runner",
        )
    )

    try:
        await asyncio.wait_for(response_received.wait(), timeout=10.0)
        log(f"Post-idle conversation turn successful: '{received_text[:80]}'")
    except asyncio.TimeoutError:
        log("⚠ Post-idle conversation turn timed out after 10s!")

    # -------------------------------------------------------------------------
    # STEP 5: LOG ANALYSIS
    # -------------------------------------------------------------------------
    log("\n" + "=" * 60)
    log("STEP 5: LOG ANALYSIS")
    log("=" * 60)

    # Check friday-errors.log
    errors_log_path = log_dir / "friday-errors.log"
    recent_errors = []
    if errors_log_path.exists():
        with open(errors_log_path, "r", encoding="utf-8", errors="ignore") as ef:
            for l in ef:
                if any(w in l.upper() for w in ["ERROR", "CRITICAL", "DEADLOCK", "TIMEOUT"]):
                    recent_errors.append(l.strip())

    log(f"Total error lines in friday-errors.log: {len(recent_errors)}")
    log(f"Errors captured during idle window: {len(errors_recorded)}")

    # -------------------------------------------------------------------------
    # STEP 6: FINAL VERDICT
    # -------------------------------------------------------------------------
    await app.stop()
    log_file.close()

    step1_pass = pre_elapsed < 2.0 and client_active and bus_started
    step2_pass = total_idle_elapsed >= 390.0 and len(errors_recorded) == 0
    step3_pass = post_elapsed < 2.0 and len(post_content) > 0
    step4_pass = health and bus_active and response_received.is_set()
    step5_pass = len(errors_recorded) == 0

    overall_pass = step1_pass and step2_pass and step3_pass and step4_pass and step5_pass

    print("\n" + "=" * 60)
    print("ITEM 5 OVERALL VERDICT")
    print("=" * 60)
    print(f"Pre-idle baseline (< 2s):       {'✓ PASS' if step1_pass else 'FAIL'} ({pre_elapsed:.2f}s)")
    print(f"Idle period (>= 390s, 0 err):   {'✓ PASS' if step2_pass else 'FAIL'} ({total_idle_elapsed:.1f}s)")
    print(f"Post-idle response (< 2s):      {'✓ PASS' if step3_pass else 'FAIL'} ({post_elapsed:.2f}s)")
    print(f"State integrity (all systems):  {'✓ PASS' if step4_pass else 'FAIL'}")
    print(f"Log analysis (0 idle errors):   {'✓ PASS' if step5_pass else 'FAIL'}")
    print(f"OVERALL STATUS:                 {'✓ PASSED' if overall_pass else 'FAIL'}")
    print("=" * 60)

    return overall_pass


if __name__ == "__main__":
    success = asyncio.run(run_item5_idle_suite())
    sys.exit(0 if success else 1)
