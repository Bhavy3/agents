from __future__ import annotations

from typing import Any, TypeAlias
from core.events.event_types import EventType
from core.exceptions import ValidationError

PayloadSchema: TypeAlias = dict[str, type | tuple[type, ...]]

EVENT_CONTRACTS: dict[EventType, PayloadSchema] = {
    EventType.USER_TEXT_RECEIVED: {"text": str},
    EventType.INTENT_DETECTED: {
        "intent": str,
        "confidence": (float, int),
        "parameters": dict,
    },
    EventType.COMMAND_EXECUTED: {
        "intent": str,
        "success": bool,
        "message": str,
    },
    EventType.RESPONSE_READY: {"text": str},
    EventType.ERROR_OCCURRED: {"error": str, "component": str},
    EventType.LLM_REQUEST_SENT: {"model": str, "prompt_preview": str},
    EventType.LLM_RESPONSE_RECEIVED: {
        "intent": str,
        "confidence": (float, int),
        "latency": (float, int),
    },
    EventType.LLM_FAILURE: {"error": str, "model": str},
    EventType.STREAM_STARTED: {"stream_id": str, "model": str},
    EventType.STREAM_CHUNK: {"stream_id": str, "chunk": str, "index": int},
    EventType.STREAM_COMPLETED: {
        "stream_id": str,
        "full_text": str,
        "chunk_count": int,
        "duration": (float, int),
        "cancelled": bool,
        "timed_out": bool,
        "degraded_mode": bool,
    },
    EventType.STREAM_CANCELLED: {"stream_id": str, "reason": str},
    EventType.STREAM_TIMEOUT: {"stream_id": str, "timeout_type": str},
    EventType.STREAM_FAILED: {"stream_id": str, "error": str},
    EventType.AUDIO_STREAM_STARTED: {"device_id": (int, str, type(None)), "sample_rate": int, "channels": int},
    EventType.AUDIO_CHUNK_RECEIVED: {"chunk_size": int, "timestamp": float, "amplitude": float, "data": bytes},
    EventType.AUDIO_BUFFER_OVERFLOW: {"dropped_chunks": int, "reason": str},
    EventType.AUDIO_STREAM_STOPPED: {"reason": str, "duration": float, "total_chunks": int},
    EventType.AUDIO_DEVICE_ERROR: {"error": str, "device_id": (int, str, type(None))},
    EventType.AUDIO_STREAM_TIMEOUT: {"timeout_type": str},
    EventType.AUDIO_STREAM_INTERRUPTED: {"reason": str},
    EventType.SPEECH_STARTED: {"timestamp": float, "amplitude": float},
    EventType.SPEECH_ENDED: {"timestamp": float, "duration": float},
    EventType.SPEECH_SEGMENT_READY: {"duration": float, "chunk_count": int, "segment_id": str, "audio_data": bytes},
    EventType.SPEECH_TIMEOUT: {"reason": str, "duration": float},
    EventType.SPEECH_INTERRUPTED: {"reason": str, "segment_id": str},
    EventType.SPEECH_NOISE_REJECTED: {"duration": float, "max_amplitude": float, "reason": str},
    EventType.STT_TRANSCRIPTION_STARTED: {"segment_id": str},
    EventType.STT_PARTIAL_TRANSCRIPT: {"segment_id": str, "text": str},
    EventType.STT_FINAL_TRANSCRIPT: {"segment_id": str, "text": str, "duration": float, "confidence": float},
    EventType.STT_TIMEOUT: {"segment_id": str, "reason": str},
    EventType.STT_INTERRUPTED: {"segment_id": str, "reason": str},
    EventType.STT_MODEL_ERROR: {"error": str},
    EventType.STT_SEGMENT_DROPPED: {"segment_id": str, "reason": str},
    EventType.CONVERSATION_TURN_STARTED: {"turn_id": str, "speaker": str},
    EventType.CONVERSATION_TURN_ENDED: {"turn_id": str, "duration": float},
    EventType.USER_MESSAGE_RECEIVED: {"text": str, "turn_id": str},
    EventType.ASSISTANT_RESPONSE_STARTED: {"turn_id": str},
    EventType.ASSISTANT_RESPONSE_PARTIAL: {"text": str, "turn_id": str},
    EventType.ASSISTANT_RESPONSE_COMPLETED: {"text": str, "turn_id": str},
    EventType.ASSISTANT_RESPONSE_CANCELLED: {"reason": str, "turn_id": str},
    EventType.CONVERSATION_INTERRUPTED: {"turn_id": str, "reason": str},
    EventType.CONVERSATION_TIMEOUT: {"timeout_type": str, "turn_id": str},
    EventType.TTS_SYNTHESIS_STARTED: {"text": str},
    EventType.TTS_AUDIO_CHUNK_READY: {"chunk_id": str, "audio_data": bytes},
    EventType.TTS_PLAYBACK_STARTED: {"chunk_id": str},
    EventType.TTS_PLAYBACK_COMPLETED: {"chunk_id": str},
    EventType.TTS_PLAYBACK_CANCELLED: {"reason": str},
    EventType.TTS_TIMEOUT: {"timeout_type": str},
    EventType.TTS_MODEL_ERROR: {"error": str},
    EventType.TTS_QUEUE_DROPPED: {"reason": str},

    # Memory
    EventType.MEMORY_WRITE_REQUEST: {"type": str, "content": str},
    EventType.MEMORY_WRITE_COMPLETED: {"id": str, "latency_ms": float},
    EventType.MEMORY_QUERY_REQUEST: {"query": str},
    EventType.MEMORY_QUERY_RESULT: {"results": list, "latency_ms": float},
    EventType.MEMORY_DENIED: {"id": str, "reason": str},
    EventType.MEMORY_FAILURE: {"operation": str, "error": str},
    EventType.MEMORY_CONTEXT_READY: {"context": str},

    # Vision
    EventType.SCREEN_CAPTURE_REQUESTED: {},
    EventType.SCREEN_CAPTURE_COMPLETED: {"image_bytes": bytes, "width": int, "height": int},
    EventType.SCREEN_CAPTURE_FAILED: {"error": str},
    EventType.OCR_REQUESTED: {"image_bytes": bytes},
    EventType.OCR_COMPLETED: {"text": str, "latency_ms": float},
    EventType.OCR_FAILED: {"error": str},
    EventType.WINDOW_FOCUS_CHANGED: {"title": str},
    EventType.ACTIVE_WINDOW_CONTEXT_READY: {"title": str, "app_name": str},
    EventType.VISUAL_CONTEXT_REQUESTED: {},
    EventType.VISUAL_CONTEXT_READY: {"summary": str},
    EventType.VISION_DEGRADED_MODE: {"reason": str, "component": str},

    # Action Runtime
    EventType.ACTION_REQUESTED: {"intent": str, "parameters": dict},
    EventType.ACTION_VALIDATED: {"tool_name": str, "risk_level": str},
    EventType.ACTION_STARTED: {"tool_name": str},
    EventType.ACTION_COMPLETED: {"success": bool, "output": str, "error": (str, type(None))},
    EventType.ACTION_FAILED: {"error": str},
    EventType.ACTION_CANCELLED: {"tool_name": str},
    EventType.ACTION_TIMEOUT: {"tool_name": str},
    EventType.ACTION_DENIED: {"reason": str, "tool_name": str},
    EventType.ACTION_CONFIRMATION_REQUIRED: {"correlation_id": str, "tool_name": str, "risk_level": str},
    EventType.ACTION_GRAPH_STARTED: {"graph_id": str, "node_count": int},
    EventType.ACTION_GRAPH_COMPLETED: {"graph_id": str, "success": bool},
    EventType.ACTION_GRAPH_FAILED: {"graph_id": str, "error": str},

    # Personality & Presence
    EventType.PERSONALITY_STYLE_UPDATED: {"persona_mode": str, "emotion_state": str, "style_config": dict},
    EventType.EMOTION_DETECTED: {"emotion": str, "confidence": float},
    EventType.PRESENCE_MODE_CHANGED: {"mode": str},
}

def validate_event_payload(event_type: EventType, payload: dict[str, Any]) -> None:
    schema = EVENT_CONTRACTS.get(event_type)
    if not schema:
        return

    for field, expected_type in schema.items():
        if field not in payload:
            raise ValidationError(f"Missing required field '{field}' for event {event_type}")
        if not isinstance(payload[field], expected_type):
            actual_type = type(payload[field]).__name__
            raise ValidationError(
                f"Invalid type for field '{field}' in event {event_type}. "
                f"Expected {expected_type}, got {actual_type}"
            )
