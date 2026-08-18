import asyncio
import time
import random
import uuid
import pytest
from dataclasses import dataclass
from typing import List, Dict, Any

from core.events.bus import EventBus
from core.events.event_types import EventType
from core.events.models import Event, EventPriority
from core.cognition.cognitive_worker import CognitiveWorker
from core.cognition.cognitive_state import TurnState
from core.audio.tts import TtsWorker
from core.orchestrator.conversation import OrchestratorWorker
from core.router.intent_router import IntentRouter
from core.llm.streaming_worker import StreamingLlmWorker

@dataclass
class AuditResult:
    timestamp: float
    split_brain: bool
    dual_ownership: bool
    ghost_playback: bool
    queue_backlog: int
    errors: List[str]

class SystemAuditor:
    def __init__(self, bus: EventBus, cognition: CognitiveWorker, orchestrator: OrchestratorWorker, tts: TtsWorker):
        self.bus = bus
        self.cognition = cognition
        self.orchestrator = orchestrator
        self.tts = tts
        self.results: List[AuditResult] = []
        self._running = False

    async def start(self):
        self._running = True
        asyncio.create_task(self._audit_loop())

    async def stop(self):
        self._running = False

    async def _audit_loop(self):
        while self._running:
            state = await self.cognition.state_engine.get_state()
            
            errors = []
            split_brain = False
            dual_ownership = False
            ghost_playback = False
            
            # 1. Dual Ownership Check
            if state.speaking and state.listening:
                dual_ownership = True
                errors.append("CRITICAL: Speaking and Listening simultaneously in cognitive state")
            
            # 2. Split Brain: Orchestrator vs Cognition
            if state.active_speaker != self.orchestrator.active_speaker:
                # Give 50ms grace for event propagation
                await asyncio.sleep(0.05)
                state = await self.cognition.state_engine.get_state()
                if state.active_speaker != self.orchestrator.active_speaker:
                    split_brain = True
                    errors.append(f"SPLIT BRAIN: Cognition says {state.active_speaker}, Orchestrator says {self.orchestrator.active_speaker}")

            # 3. Ghost Playback Check
            if state.active_speaker == "user" and self.tts.playback_active:
                ghost_playback = True
                errors.append("GHOST PLAYBACK: TTS active while user is speaking")

            self.results.append(AuditResult(
                timestamp=time.time(),
                split_brain=split_brain,
                dual_ownership=dual_ownership,
                ghost_playback=ghost_playback,
                queue_backlog=self.bus._queue.qsize(),
                errors=errors
            ))
            await asyncio.sleep(0.01) # High frequency audit

@pytest.mark.asyncio
async def test_hard_concurrency_stress_test():
    print("CORE HARD CONCURRENCY STRESS TEST (PHASE 13.0.1)")
    
    bus = EventBus(max_queue_size=20000)
    await bus.start()
    
    # Setup real workers for synchronization check
    cognition = CognitiveWorker(bus)
    
    # Mock dependencies for Orchestrator
    intent_router = IntentRouter(bus)
    streaming_worker = StreamingLlmWorker(bus, None, None) # Mock client/aggregator
    orchestrator = OrchestratorWorker(bus, intent_router, streaming_worker)
    
    tts = TtsWorker(bus, model_path=None) # Degraded mode
    
    # Start all
    await cognition.start()
    await orchestrator.start()
    await tts.start()
    
    auditor = SystemAuditor(bus, cognition, orchestrator, tts)
    await auditor.start()
    
    await asyncio.sleep(0.5)
    
    print("\nSTEP 1: THE BIG COLLISION (Simultaneous injection)")
    
    async def inject_event(event_type, payload, source, delay=0):
        if delay: await asyncio.sleep(delay)
        await bus.publish(Event.create(event_type, payload, source))

    collision_tasks = [
        inject_event(EventType.USER_SPEECH, {"status": "started", "amplitude": 0.9, "timestamp": time.time()}, "vad"),
        inject_event(EventType.ASSISTANT_RESPONSE, {"status": "completed", "turn_id": "turn_1", "text": "response"}, "orchestrator"),
        inject_event(EventType.TTS_PLAY, {"status": "started"}, "tts"),
        inject_event(EventType.ACTION_REQUEST, {"intent": "disk_scan"}, "tools"),
        inject_event(EventType.ACTION_RESULT, {"status": "success", "result": "ok"}, "workflow")
    ]
    
    print("Firing simultaneous events...")
    await asyncio.gather(*collision_tasks)
    await asyncio.sleep(0.2) # Let it settle
    
    print("\nSTEP 2: SATURATION BURST (1,000 events for unit test speed)")
    print("Injecting 1,000 mixed priority events...")
    
    burst_tasks = []
    for i in range(1000):
        etype = random.choice([
            EventType.USER_SPEECH,
            EventType.ASSISTANT_RESPONSE
        ])
        
        if etype == EventType.USER_SPEECH:
            payload = random.choice([
                {"status": "started", "timestamp": time.time(), "amplitude": 0.5},
                {"status": "partial", "text": "test"},
                {"status": "final", "text": "test"}
            ])
        else: # ASSISTANT_RESPONSE
            payload = {"status": "completed", "turn_id": "turn_1", "text": "test"}
            
        burst_tasks.append(inject_event(etype, payload, "chaos", delay=random.uniform(0, 0.05)))

    await asyncio.gather(*burst_tasks)
    print("Burst finished. Waiting for queue to stabilize...")
    
    timeout = 5.0
    start_wait = time.time()
    while bus._queue.qsize() > 0 and time.time() - start_wait < timeout:
        await asyncio.sleep(0.2)
        print(f"Queue size: {bus._queue.qsize()}")

    # Clean up any pending tasks from Step 2 to ensure Step 3 is clean and deterministic
    if getattr(orchestrator, "_turn_hold_task", None) and not orchestrator._turn_hold_task.done():
        orchestrator._turn_hold_task.cancel()
    if hasattr(orchestrator, "_pending_turn_text"):
        orchestrator._pending_turn_text.clear()
    orchestrator.active_speaker = None
    await cognition.state_engine.update_state(active_speaker=None, speaking=False, listening=False)

    print("\nSTEP 3: DELAYED RESURRECTION CHECK")
    await bus.publish(Event.create(EventType.USER_SPEECH, {"status": "started", "amplitude": 0.9, "timestamp": time.time()}, "vad"))
    await asyncio.sleep(0.05)
    await bus.publish(Event.create(EventType.ASSISTANT_RESPONSE, {"status": "partial", "turn_id": "turn_1", "text": "I shouldn't be here"}, "orchestrator"))
    await asyncio.sleep(0.1)
    
    print("\nFINAL AUDIT ANALYSIS")
    await auditor.stop()
    
    total_audits = len(auditor.results)
    failures = [r for r in auditor.results if r.errors]
    
    split_brains = sum(1 for r in auditor.results if r.split_brain)
    dual_ownerships = sum(1 for r in auditor.results if r.dual_ownership)
    ghosts = sum(1 for r in auditor.results if r.ghost_playback)
    
    print(f"Total Audit Points: {total_audits}")
    print(f"Failures Detected: {len(failures)}")
    print(f"  - Split Brains: {split_brains}")
    print(f"  - Dual Ownerships: {dual_ownerships}")
    print(f"  - Ghost Playbacks: {ghosts}")
    
    await cognition.stop()
    await orchestrator.stop()
    await tts.stop()
    await bus.stop()

    assert len(failures) == 0, f"System has race conditions: {failures[:3]}"
