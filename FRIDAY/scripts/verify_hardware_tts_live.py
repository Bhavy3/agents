import asyncio
import logging
import sys
import time
from pathlib import Path

# Add project root to sys.path
root_dir = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root_dir))

from core.audio.pipecat_worker import PipecatAudioWorker
from core.audio.tts import TtsWorker
from core.config.settings import load_settings
from core.events.bus import EventBus
from core.events.event_types import EventType
from core.events.models import Event
from core.logging.logger import get_logger
from core.metrics.metrics import RuntimeMetrics
from interfaces.cli.health_dashboard import TerminalHealthDashboard
from core.workers.supervisor import WorkerSupervisor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)

logger = logging.getLogger("verify_hardware_tts_live")

async def run_live_test():
    settings = load_settings()
    root_dir = Path(__file__).resolve().parents[1]
    tts_model_path = str(root_dir / "data" / "models" / "tts" / "en_US-hfc_female-medium.onnx")
    tts_config_path = tts_model_path + ".json"

    print("=" * 80)
    print("LIVE HARDWARE TTS STREAM END VERIFICATION")
    print(f"TTS Model: {tts_model_path}")
    print("=" * 80)

    metrics = RuntimeMetrics()
    bus = EventBus(metrics=metrics)
    await bus.start()

    tts_worker = TtsWorker(
        bus,
        model_path=tts_model_path,
        config_path=tts_config_path,
    )

    pipecat_worker = PipecatAudioWorker(bus)
    supervisor = WorkerSupervisor(bus, workers=[tts_worker, pipecat_worker], metrics=metrics)
    dashboard = TerminalHealthDashboard(bus, metrics, supervisor)

    completed_events = []
    safety_net_events = []

    async def on_playback_completed(event: Event):
        payload = event.payload
        print(f"\n>>> [EVENT RECEIVED] TTS_PLAYBACK_COMPLETED: turn_id={payload.get('turn_id')} chunk_id={payload.get('chunk_id')}")
        completed_events.append(event)

    async def on_stream_end(event: Event):
        payload = event.payload
        print(f"\n>>> [EVENT RECEIVED] TTS_STREAM_END: turn_id={payload.get('turn_id')}")

    bus.subscribe(EventType.TTS_PLAYBACK_COMPLETED, on_playback_completed)
    bus.subscribe(EventType.TTS_STREAM_END, on_stream_end)

    # Start workers
    tts_task = asyncio.create_task(tts_worker.run())
    pipecat_task = asyncio.create_task(pipecat_worker.run())

    # Wait for workers and Piper warmup
    await asyncio.sleep(2.0)
    print("\n--- Pipeline and TTS initialization complete. Starting scenarios ---\n")

    # =========================================================================
    # SCENARIO 1: Short / One-word response ("Hello.")
    # =========================================================================
    print("\n" + "=" * 60)
    print("SCENARIO 1: SHORT RESPONSE ('Hello.')")
    print("=" * 60)
    turn_1 = "live_short_1"
    completed_before = len(completed_events)

    await bus.publish(Event.create(EventType.CONVERSATION_TURN_STARTED, {"turn_id": turn_1, "speaker": "user"}, "orchestrator"))
    await bus.publish(Event.create(EventType.ASSISTANT_RESPONSE_PARTIAL, {"turn_id": turn_1, "text": "Hello. "}, "orchestrator"))
    await bus.publish(Event.create(EventType.ASSISTANT_RESPONSE_COMPLETED, {"turn_id": turn_1, "text": "Hello."}, "orchestrator"))

    # Wait for completion
    for _ in range(50):
        if len(completed_events) > completed_before:
            break
        await asyncio.sleep(0.1)

    print("Waiting 3.0s extra to ensure 2.5s safety net DOES NOT fire...")
    await asyncio.sleep(3.0)

    print(f"Scenario 1 finished. Stream end fires: {pipecat_worker.stream_end_fires}, Safety net fires: {pipecat_worker.safety_net_fires}")
    assert pipecat_worker.safety_net_fires == 0, "Safety net fired during Scenario 1!"
    assert len(completed_events) == completed_before + 1, "Scenario 1 did not complete!"

    # =========================================================================
    # SCENARIO 2: Long multi-sentence response (11 sentences)
    # =========================================================================
    print("\n" + "=" * 60)
    print("SCENARIO 2: LONG MULTI-SENTENCE RESPONSE (11 sentences)")
    print("=" * 60)
    turn_2 = "live_long_2"
    completed_before = len(completed_events)

    sentences = [
        "Sentence one begins the live hardware response. ",
        "Sentence two demonstrates sustained stream processing. ",
        "Sentence three validates continuous synthesis and buffering. ",
        "Sentence four ensures prosody boundaries remain intact. ",
        "Sentence five tests intermediate sentence queuing. ",
        "Sentence six verifies that the lock prevents re-ordering. ",
        "Sentence seven confirms audio output buffer stability. ",
        "Sentence eight proves Piper chunks are streamed seamlessly. ",
        "Sentence nine tests the final sentence generation. ",
        "Sentence ten checks the end of turn marker sequencing. ",
        "Sentence eleven concludes the sustained multi-sentence test."
    ]

    await bus.publish(Event.create(EventType.CONVERSATION_TURN_STARTED, {"turn_id": turn_2, "speaker": "user"}, "orchestrator"))
    
    # Stream chunks progressively like real LLM streaming
    for s in sentences:
        await bus.publish(Event.create(EventType.ASSISTANT_RESPONSE_PARTIAL, {"turn_id": turn_2, "text": s}, "orchestrator"))
        await asyncio.sleep(0.08)

    await bus.publish(Event.create(EventType.ASSISTANT_RESPONSE_COMPLETED, {"turn_id": turn_2, "text": "".join(sentences)}, "orchestrator"))

    for _ in range(120):
        if len(completed_events) > completed_before:
            break
        await asyncio.sleep(0.1)

    print("Waiting 3.0s extra to ensure 2.5s safety net DOES NOT fire...")
    await asyncio.sleep(3.0)

    print(f"Scenario 2 finished. Stream end fires: {pipecat_worker.stream_end_fires}, Safety net fires: {pipecat_worker.safety_net_fires}")
    assert pipecat_worker.safety_net_fires == 0, "Safety net fired during Scenario 2!"
    assert len(completed_events) == completed_before + 1, "Scenario 2 did not complete!"

    # =========================================================================
    # SCENARIO 3: Three rapid consecutive turns back to back
    # =========================================================================
    print("\n" + "=" * 60)
    print("SCENARIO 3: THREE RAPID CONSECUTIVE TURNS BACK TO BACK")
    print("=" * 60)
    completed_before = len(completed_events)

    rapid_turns = [
        ("live_rapid_3a", "First rapid acknowledgment. "),
        ("live_rapid_3b", "Second rapid update here. "),
        ("live_rapid_3c", "Third and final rapid confirmation.")
    ]

    for turn_id, text in rapid_turns:
        print(f"Initiating {turn_id}: '{text.strip()}'")
        await bus.publish(Event.create(EventType.CONVERSATION_TURN_STARTED, {"turn_id": turn_id, "speaker": "user"}, "orchestrator"))
        await bus.publish(Event.create(EventType.ASSISTANT_RESPONSE_PARTIAL, {"turn_id": turn_id, "text": text}, "orchestrator"))
        await bus.publish(Event.create(EventType.ASSISTANT_RESPONSE_COMPLETED, {"turn_id": turn_id, "text": text.strip()}, "orchestrator"))
        # Minimal delay between turns to stress test concurrency
        await asyncio.sleep(0.4)

    for _ in range(80):
        if len(completed_events) >= completed_before + 3:
            break
        await asyncio.sleep(0.1)

    print("Waiting 3.0s extra to ensure 2.5s safety net DOES NOT fire...")
    await asyncio.sleep(3.0)

    print(f"Scenario 3 finished. Stream end fires: {pipecat_worker.stream_end_fires}, Safety net fires: {pipecat_worker.safety_net_fires}")
    assert pipecat_worker.safety_net_fires == 0, "Safety net fired during Scenario 3!"
    assert len(completed_events) == completed_before + 3, "Scenario 3 did not complete all 3 turns!"

    # =========================================================================
    # CLI STATUS & METRICS REPORT
    # =========================================================================
    print("\n" + "=" * 80)
    print("FINAL CLI DASHBOARD STATUS:")
    print("=" * 80)
    print(dashboard.render())

    print("\n" + "=" * 80)
    print("FINAL CLI DASHBOARD METRICS:")
    print("=" * 80)
    print(dashboard.render_metrics())

    # Final assertions
    print("\n" + "=" * 80)
    print(f"FINAL TOTALS: stream_end_fires={pipecat_worker.stream_end_fires} | safety_net_fires={pipecat_worker.safety_net_fires}")
    print(f"Safety Net Ratio: {metrics.tts_safety_net_ratio:.4f}")
    print("=" * 80)

    # Cleanup
    await tts_worker.stop()
    await pipecat_worker.stop()
    await tts_task
    await pipecat_task
    await bus.stop()

    if pipecat_worker.safety_net_fires == 0 and pipecat_worker.stream_end_fires == 5:
        print("\n>>> ALL THREE SCENARIOS PASSED WITH ZERO SAFETY-NET TRIGGERS (100% STREAM_END FIRES)! <<<")
        return 0
    else:
        print("\n>>> FAILURE: Safety net fired or missing stream end fires! <<<")
        return 1

if __name__ == "__main__":
    code = asyncio.run(run_live_test())
    sys.exit(code)
