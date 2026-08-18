# FRIDAY Conversational Pipeline Debug Guide

## Implementation Complete

All critical debug logging has been added to trace the full conversational pipeline from audio input to speech output.

## Pipeline Trace Points

### Entry Point: Audio Transport
- **File**: `core/audio/transport.py`
- **What**: Captures audio from microphone
- **Emits**: `AUDIO_CHUNK` with `type="audio_raw"`
- **Status**: ✅ Working (chunks visible in startup logs)

### Stage 1: Voice Activity Detection (VAD)
- **File**: `core/audio/vad.py`
- **What**: Detects speech start/end
- **Subscribes to**: `AUDIO_CHUNK` with `type="audio_raw"`
- **Emits**:
  1. `USER_SPEECH` with `status="started"` when speech detected
  2. `USER_SPEECH` with `status="ended"` when speech ends
  3. `AUDIO_CHUNK` with `type="segment"` containing collected audio
- **Debug Logs**: 
  - `vad_segment_finalized` [id, duration, confidence]
  - `vad_emitting_segment_chunk` [id, audio_bytes]

### Stage 2: Speech-to-Text (STT)
- **File**: `core/audio/stt.py`
- **What**: Transcribes audio to text
- **Subscribes to**: `AUDIO_CHUNK` with `type="segment"`
- **Emits**: `USER_SPEECH` with `status="final"` and `text="..."`
- **Debug Logs**:
  - `stt_segment_received` [id, audio_bytes]
  - `stt_final` [id, text, latency_ms]
  - `stt_emitting_user_speech` [full payload]

### Stage 3: Orchestrator (Conversation Coordinator)
- **File**: `core/orchestrator/conversation.py`
- **What**: Receives text, routes to LLM, coordinates response
- **Subscribes to**: `USER_SPEECH` with all statuses
- **Emits**: `ACTION_REQUEST` (for workflows) or routes to LLM via `intent_router`
- **Debug Logs**:
  - `orchestrator_user_speech` [status, payload_keys]
  - `orchestrator_speech_final` [text, full payload]
  - `orchestrator_scheduling_turn_finalization` [text]
  - `orchestrator_waiting_for_turn_finalization` [hold_ms]
  - `orchestrator_initiating_turn` [text, correlation_id]
  - `orchestrator_route_execute_start` [turn_id, text, correlation_id]
  - `orchestrator_text_resolved` [was_resolved, original, resolved]
  - `orchestrator_routing_to_intent_router` [text]
  - `orchestrator_intent_routed` [intent]
  - `orchestrator_calling_handle_user_text`

### Stage 4: Intent Router & LLM Invocation
- **Files**: 
  - `core/router/intent_router.py` (routes to appropriate handler)
  - `core/llm/streaming_worker.py` (streams LLM response)
- **What**: Routes intent and invokes LLM for response generation
- **Emits**: `ASSISTANT_RESPONSE` with `status="started|partial|completed"`
- **Debug Logs**:
  - `streaming_worker_start_stream` [prompt_len, correlation_id]
  - `streaming_worker_complete` [stream_id, result_len]
  - `aggregator_start_stream` [id, model, correlation_id]
  - `aggregator_stream_complete` [id, chunks, duration_ms, text]

### Stage 5: Text-to-Speech (TTS)
- **File**: `core/audio/tts.py`
- **What**: Converts response text to speech output
- **Subscribes to**: `ASSISTANT_RESPONSE` with `status="completed"`
- **Emits**: Audio playback (Piper TTS or degraded mode)
- **Debug Logs**:
  - `tts_assistant_response` [status, payload_keys]
  - `tts_response_complete` [text_len, text preview]

## How to Diagnose Pipeline Breaks

### 1. Audio Not Being Captured
- Check logs for: `audio_transport_started` 
- Look for: `AUDIO_CHUNK` events in logs
- If missing: Microphone/sounddevice not working

### 2. VAD Not Detecting Speech
- Check for: `vad_segment_finalized` logs
- Expected: Should appear after ~500ms of speech
- If missing: Check confidence threshold or silence_threshold settings

### 3. STT Not Transcribing
- Check for: `stt_segment_received` logs
- Then: `stt_final` logs with text
- If missing: Whisper model not initialized or audio data corrupted

### 4. Orchestrator Not Receiving
- Check for: `orchestrator_user_speech` logs
- Expected status: "final" with non-empty text
- If missing: Event didn't reach orchestrator (subscription issue)

### 5. LLM Not Responding
- Check for: `streaming_worker_start_stream` logs
- Check for: `aggregator_stream_complete` logs
- If missing: Intent router not invoking LLM (check intent routing)
- Check Ollama health: `ollama_health_check [available=...]`

### 6. TTS Not Speaking
- Check for: `tts_assistant_response` logs with status="completed"
- Check for: `tts_response_complete` logs with text
- If missing: LLM response didn't reach TTS

## Event Payload Schemas (Critical!)

### USER_SPEECH
```python
{
    "status": "started" | "final" | "ended",
    "text": "...",  # Only in status="final"
    "segment_id": "...",
    "timestamp": float,
    "duration": float,  # In seconds
    "confidence": float,  # 0.0-1.0
}
```

### ASSISTANT_RESPONSE
```python
{
    "status": "started" | "partial" | "completed",
    "stream_id": "...",
    "text": "...",  # Partial or final text
    "turn_id": "...",
    "duration_ms": float,  # Only in completed
    "chunk_count": int,  # Only in completed
}
```

### AUDIO_CHUNK
```python
{
    "type": "audio_raw" | "segment",
    "audio_data": bytes,
    "duration": float,  # In seconds
    "segment_id": "...",  # Only in type="segment"
    "amplitude": float,  # For raw chunks
    "timestamp": float,
}
```

## Running Diagnostics

### Option 1: Test Command via CLI
```
cd FRIDAY
python main.py
> You: test
```
Watch the logs for the CRITICAL messages tracing through the pipeline.

### Option 2: Check Specific Component
```bash
# Verify STT model loaded
python -c "from faster_whisper import WhisperModel; m = WhisperModel('tiny.en'); print('STT OK')"

# Check Ollama availability
curl http://localhost:11434/api/tags
```

### Option 3: Runtime Validation
```bash
python main.py --burn-in --duration-seconds 300
```
Runs automated test pipeline with diagnostics.

## Key Metrics to Watch

- **Audio Chunks**: Should be continuously captured (every ~64ms at 16kHz)
- **VAD Segments**: Should trigger when speech detected
- **STT Latency**: Should be < 500ms for "tiny" model
- **Orchestrator Routing**: Turn initialization should be < 400ms
- **LLM Generation**: Depends on Ollama response time
- **TTS Playback**: Should start within 1-2 seconds of response completion

## Reducing Log Spam

The heartbeat logs are now minimized:
- Only logs when worker state actually changes
- Silent heartbeat updates no longer emit `worker_state_transition`
- Audio transport buffer status still visible for debugging

## Next Steps After Debug

1. **When pipeline works**: Confirm all CRITICAL logs appear in order
2. **Identify blockage**: See which stage logs stop appearing
3. **Fix root cause**: Refer to new_face.md rules for surgical fixes
4. **Run burn-in test**: Validate stability with --burn-in flag
5. **Remove debug logs**: Once root cause fixed, can remove CRITICAL logs or set to DEBUG level
