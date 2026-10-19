# FRIDAY Omega Pending List

This is the plain status list for the ten Omega objectives. A goal is only
marked complete when the repository has a passing check and the required live
evidence. A passing unit test alone does not prove hardware, long-session, or
human-experience behavior.

## Current status

1. **Omega 1 - Realtime presence: PARTIAL**
   - The live route now uses `PresenceTimingEngine` and `ResponseReadinessGate`.
   - Readiness waits are cancelled by interruption and covered by a live-path synthetic regression test.
   - Live conversational continuity and real audio acknowledgment are not verified.

2. **Omega 2 - Latency domination: PARTIAL**
   - Bounded p50/p95 turn telemetry now exists and records intent, first response, TTS start, and terminal timing.
   - Clear static chat/general-question turns now bypass the duplicate classifier request and go directly to one answer stream; action-like and dynamic questions still use the classifier.
   - Live llama.cpp baseline is now available: mean streaming first SSE chunk **0.06 s**, mean total response **0.81 s** across five queries.
   - Live full-app arithmetic probe after the fast path measured **979.7 ms** to `RESPONSE_READY`, with zero failed events. This is improved from the audited ~2.8 s path but remains above the strict 500 ms voice target.
   - A direct content-bearing stream probe measured first content at about **1.70 s** and total about **1.81 s**; the distinction between first SSE metadata and first content still needs standardized measurement.
   - VAD, STT, and TTS hardware target measurements are not yet collected.

3. **Omega 3 - Conversational stability: IMPROVED / PARTIAL**
   - The app now injects one `CognitiveStateEngine` into both the cognitive worker and orchestrator.
   - Canonical lifecycle events, stale completion protection, readiness cancellation, and AEC VAD fallback are covered synthetically.
   - Real overlapping speech and speaker-output behavior are not verified.

4. **Omega 4 - Long-term cognitive memory: PARTIAL**
   - SQLite persistence, ranking, decay, compression, approval, and bounded recall are tested.
   - Months-long continuity and distinct strategic, behavioral, emotional, and operational layers are not verified.

5. **Omega 5 - Autonomous workflow intelligence: IMPROVED / PARTIAL**
   - Planning, chaining, retry, interruption, safety, persistence, and conservative restart recovery are tested.
   - Completed steps are preserved, confirmation gates are not replayed, idempotent in-flight work may resume, and unsafe in-flight work fails explicitly.
   - The complete real repository-fix flow is not verified end to end.

6. **Omega 6 - Emotional presence: PARTIAL**
   - Tone detection and delivery-only style modulation are tested.
   - Real adaptive delivery and human evaluation are not verified.

7. **Omega 7 - Production survival: PARTIAL**
   - Worker supervision, restart, quarantine, diagnostics, and short burn-in tests exist.
   - Model escalation now validates paths, uses configurable GPU layers, requires HTTP 200 health, and rolls back after failed target startup.
   - Eight-hour soak, sustained memory pressure, live 7B fit on the RTX 3050 4 GiB GPU, offline fallback, and watchdog evidence are pending.

8. **Omega 8 - Unified device ecosystem: PARTIAL / SCOPE BLOCKED**
   - Existing local audio, vision, desktop, filesystem, browser, API, and safety modules exist.
   - Calendar, email, WhatsApp, mobile, cloud-drive, notification, and IDE integrations are not implemented or verified.
   - The current `docs/rule_book.md` prohibits expanding those integration families without an explicit phase decision.

9. **Omega 9 - Adaptive intelligence routing: IMPROVED / PARTIAL**
   - The streaming worker now owns the logical selected model and routing reason for the next stream.
   - Stream-start events expose the selected label and configured backend model.
   - The selected adaptive model is synthetically proven to reach the active fake streaming client.
   - A single llama.cpp endpoint cannot be claimed to have changed loaded weights without a live backend capable of doing so.
   - Live app probe selected logical model `3b` with reason `medium_query_fits_budget` and reported backend model `qwen2.5-3b-instruct-q5_k_m`.

10. **Omega 10 - Illusion of life: NOT VERIFIED**
    - Supporting subsystems exist independently.
    - No composite multi-turn, memory, interruption, workflow, live-model, and hardware scorecard has passed.

## Immediate implementation order

1. Keep the shared cognitive authority and hard-concurrency invariant green under repeated stress.
2. Complete the composite synthetic Omega scorecard without treating it as hardware evidence.
3. Add explicit memory-layer metadata where it fits existing models.
4. Run live backend, audio, hardware, and soak checks where the environment provides them.
5. Update this document with actual results; leave unavailable evidence explicitly marked pending.

## Evidence already available

   - Full pytest baseline after the current increments: **294 passed, 3 warnings**.
- Focused diagnostics, model, interruption, orchestrator, routing, streaming, and cognitive tests pass.
- Text-only burn-in runs successfully with zero failed events and no detected anomalies; the runtime snapshot is JSON-serializable.
- Current environmental gaps include unavailable Tesseract, real audio hardware evidence, and the eight-hour soak.

## Newly verified live LLM evidence

- `GET http://127.0.0.1:8080/health` returned `{"status":"ok"}`.
- `/props` reported the loaded Qwen 3B GGUF, Q5_K_M quantization, context size 4096, and a Qwen chat template with system-role support.
- Non-streaming completion returned HTTP 200 and exact probe text `LIVE_LLM_OK` in about **1.90 s**.
- Streaming completion returned HTTP 200 and exact probe text `LIVE_STREAM_OK`; first content arrived in about **1.70 s**, total about **1.81 s**.
- Full app text-only probe returned a real response: `2 + 2 equals 4. This is a fundamental arithmetic operation.`
- The same app probe emitted `STREAM_STARTED` with model `3b`, routing reason `medium_query_fits_budget`, and the configured 3B backend.
- The live app probe had zero LLM failure events and zero event-handler failures.
- Audio enumeration found working input devices including `Microphone Array (Realtek(R) Audio)` and output devices including `Speakers (Realtek(R) Audio)`; actual microphone/speaker interaction is still not verified.
- The available GPU is an NVIDIA GeForce RTX 3050 Laptop GPU with **4096 MiB** total VRAM and about **2215 MiB** used during inspection; the 7B file exists, but a live 7B load has not been retried after the safe fallback change.
- The model manager now defaults to `-ngl 0` unless `FRIDAY_LLAMA_NGL` (or its documented aliases) is set, avoiding an unsafe hard-coded full offload.
- The chat-latency regression tests and model-fallback tests pass; focused regression set: **32 passed**.
- Current focused model/fast-chat regression run: **15 passed**.
- Current 2-second text-only burn-in: `failed_events=0`, `queue_depth=0`, `detected_anomalies=[]`, `restart_count=2` for the intentionally injected validation-crash worker, and `turn_telemetry_p50_ms=332.997`.

## Completion rule

FRIDAY is not 100% Omega-complete until every item has both passing automated
acceptance checks and the required live evidence. No synthetic result is to be
reported as real hardware, long-soak, or human-experience evidence.
