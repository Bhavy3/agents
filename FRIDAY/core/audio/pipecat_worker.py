import asyncio
import time
import uuid
import difflib
import audioop
from collections import deque

try:
    from aec_audio_processing import AudioProcessor
except ImportError:
    AudioProcessor = None

try:
    from pipecat.pipeline.pipeline import Pipeline
    from pipecat.pipeline.task import PipelineTask
    from pipecat.pipeline.runner import PipelineRunner
    from pipecat.transports.local.audio import LocalAudioTransport, LocalAudioTransportParams
    from pipecat.services.whisper.stt import WhisperSTTService
    from pipecat.audio.vad.silero import SileroVADAnalyzer
    from pipecat.audio.vad.vad_analyzer import VADParams
    from pipecat.processors.audio.vad_processor import VADProcessor
    from pipecat.processors.frame_processor import FrameProcessor
    from pipecat.frames.frames import TranscriptionFrame, AudioRawFrame, OutputAudioRawFrame, CancelFrame, InterruptionFrame
except ImportError:
    pass  # Allow tests to mock

from core.events.bus import EventBus
from core.events.event_types import EventType
from core.events.models import Event
from core.workers.base_worker import BaseWorker
from core.config.settings import load_settings

class AecProcessor(FrameProcessor):
    def __init__(self, worker: 'PipecatAudioWorker', delay_ms: int = 180, enable_ns: bool = False, enable_agc: bool = False):
        super().__init__()
        self.worker = worker
        self.logger = worker.logger
        self.aec = None
        self.enabled = False
        # Lock required: AudioProcessor is a SWIG wrapper around C++ WebRTC APM.
        # The underlying native object maintains mutable filter state (delay estimator,
        # echo path coefficients, adaptation state). process_stream() (called from
        # Pipecat's pipeline task) and process_reverse_stream() (called from
        # TtsOutputProcessor's event-bus callback task) can run in different asyncio
        # tasks. Without a lock, interleaved C++ calls corrupt internal state.
        self._aec_lock = asyncio.Lock()
        
        if AudioProcessor is not None:
            self.aec = AudioProcessor(enable_aec=True, enable_ns=enable_ns, enable_agc=enable_agc, enable_vad=False)
            self.aec.set_stream_format(16000, 1)
            self.aec.set_reverse_stream_format(16000, 1)
            self.aec.set_stream_delay(delay_ms)
            self.enabled = True
        
        self._mic_buffer = bytearray()
        self._ref_buffer = bytearray()
        self._ratecv_state = None
        self._log_counter = 0
        self._rms_window = deque(maxlen=100)
        
        self._ref_queue = asyncio.Queue()
        self._feeder_task = None
        
        self.worker.event_bus.subscribe(EventType.TTS_PLAYBACK_CANCELLED, self._handle_tts_cancelled)
        self.worker.event_bus.subscribe(EventType.CONVERSATION_INTERRUPTED, self._handle_tts_cancelled)

    async def cleanup(self) -> None:
        self.worker.event_bus.unsubscribe(EventType.TTS_PLAYBACK_CANCELLED, self._handle_tts_cancelled)
        self.worker.event_bus.unsubscribe(EventType.CONVERSATION_INTERRUPTED, self._handle_tts_cancelled)
        if self._feeder_task and not self._feeder_task.done():
            self._feeder_task.cancel()

    async def _handle_tts_cancelled(self, event: Event) -> None:
        if self._feeder_task and not self._feeder_task.done():
            self._feeder_task.cancel()
            self._feeder_task = None
        while not self._ref_queue.empty():
            try:
                self._ref_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        self._ref_buffer.clear()
        self._ratecv_state = None

    async def feed_reference(self, audio_data: bytes, sample_rate: int):
        if not self.enabled:
            return
            
        await self._ref_queue.put((audio_data, sample_rate))
        
        if self._feeder_task is None or self._feeder_task.done():
            self._feeder_task = asyncio.create_task(self._feeder_loop())
            
    async def _feeder_loop(self):
        try:
            target_time = time.perf_counter()
            while True:
                audio_data, sample_rate = await self._ref_queue.get()
                
                if sample_rate != 16000:
                    import warnings
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore", DeprecationWarning)
                        audio_data, self._ratecv_state = audioop.ratecv(
                            audio_data, 2, 1, sample_rate, 16000, self._ratecv_state
                        )
                
                self._ref_buffer.extend(audio_data)
                
                async with self._aec_lock:
                    while len(self._ref_buffer) >= 320:
                        chunk = bytes(self._ref_buffer[:320])
                        self._ref_buffer = self._ref_buffer[320:]
                        try:
                            self.aec.process_reverse_stream(chunk)
                        except Exception as e:
                            self.logger.error("aec_reverse_stream_error", extra={"error": str(e)}, exc_info=True)
                
                # Pace the feeding loop based on physical audio duration to mirror speaker output
                chunk_duration = len(audio_data) / (16000 * 2)  # 16-bit PCM (2 bytes) at 16000 Hz
                now = time.perf_counter()
                if target_time < now:
                    # We fell behind (or just starting), reset target
                    target_time = now + chunk_duration
                else:
                    target_time += chunk_duration
                    
                delay = target_time - time.perf_counter()
                if delay > 0:
                    await asyncio.sleep(delay)
                    
        except asyncio.CancelledError:
            pass

    async def process_frame(self, frame, direction):
        if not self.enabled:
            await super().process_frame(frame, direction)
            await self.push_frame(frame, direction)
            return

        frame_type = type(frame).__name__
        if frame_type in ('AudioRawFrame', 'InputAudioRawFrame'):
            self._mic_buffer.extend(frame.audio)
            
            clean_audio = bytearray()
            
            async with self._aec_lock:
                while len(self._mic_buffer) >= 320:
                    chunk = bytes(self._mic_buffer[:320])
                    self._mic_buffer = self._mic_buffer[320:]
                    
                    rms = audioop.rms(chunk, 2)
                    self._rms_window.append(rms)
                    self.worker.recent_mic_rms = max(self._rms_window) if self._rms_window else 0
                    
                    try:
                        processed_chunk = self.aec.process_stream(chunk)
                        clean_audio.extend(processed_chunk)
                        
                        self._log_counter += 1
                        if self._log_counter % 200 == 0:
                            # TUNING GUIDELINES:
                            # If aec_delay_ms is TOO LOW: Echo bursts arrive at the start of TTS before the filter adapts.
                            # If aec_delay_ms is TOO HIGH: The AEC waits too long and misses the echo entirely.
                            # Adjust by increments of 10-20ms. Target is no audible echo bleed.
                            self.logger.debug("aec_tuning_stats", extra={
                                "delay_ms": self.aec.get_stream_delay(),
                                "has_voice": self.aec.has_voice(),
                                "instructions": "Adjust FRIDAY_AEC_DELAY_MS. Too low = echo bursts at start. Too high = consistent echo bleed."
                            })
                    except Exception as e:
                        self.logger.error("aec_forward_stream_error", extra={"error": str(e)}, exc_info=True)
                        clean_audio.extend(chunk)
            
            if clean_audio:
                clean_frame = type(frame)(
                    audio=bytes(clean_audio),
                    sample_rate=16000,
                    num_channels=1
                )
                await super().process_frame(clean_frame, direction)
                await self.push_frame(clean_frame, direction)
            return
            
        await super().process_frame(frame, direction)
        await self.push_frame(frame, direction)

class MuteGateProcessor(FrameProcessor):
    def __init__(self, worker: 'PipecatAudioWorker'):
        super().__init__()
        self.worker = worker

    async def process_frame(self, frame, direction):
        frame_type = type(frame).__name__
            
        if frame_type in ('AudioRawFrame', 'InputAudioRawFrame'):
            if self.worker.is_tts_playing:
                self.worker.last_mutegate_zeroed = time.perf_counter()
                muted_audio = b'\x00' * len(frame.audio)
                frame = type(frame)(
                    audio=muted_audio,
                    sample_rate=frame.sample_rate,
                    num_channels=frame.num_channels
                )
        await super().process_frame(frame, direction)
        await self.push_frame(frame, direction)

class TranscriptionPublisher(FrameProcessor):
    def __init__(self, worker: 'PipecatAudioWorker'):
        super().__init__()
        self.worker = worker
        self.event_bus = worker.event_bus
        self.logger = worker.logger
        self.segment_start_time = time.perf_counter()

    async def process_frame(self, frame, direction):
        frame_type = type(frame).__name__
        
        if frame_type in ('UserStartedSpeakingFrame', 'VADUserStartedSpeakingFrame'):
            recent_rms = getattr(self.worker, "recent_mic_rms", 0.0)
            is_playing = self.worker.is_tts_playing
            time_since_start = -1.0
            
            if is_playing and self.worker.tts_processor and getattr(self.worker.tts_processor, "_turn_start_time", 0.0) > 0:
                time_since_start = time.perf_counter() - self.worker.tts_processor._turn_start_time
                
            mutegate_active = getattr(self.worker, "last_mutegate_zeroed", 0.0)
            was_zeroed = (time.perf_counter() - mutegate_active) < 0.1
            
            self.logger.critical(
                "\n\n=========================================\n"
                "[DIAGNOSTIC] VAD TRIGGERED ('User started speaking')\n"
                f"1. recent_mic_rms: {recent_rms}\n"
                f"2. is_tts_playing: {is_playing}\n"
                f"3. seconds_since_tts_started: {time_since_start:.3f}s\n"
                f"4. Was MuteGate zeroing frames at this moment? {was_zeroed}\n"
                "=========================================\n\n"
            )
            
            payload = {"timestamp": time.time(), "amplitude": 1.0}
            await self.event_bus.publish(Event.create(EventType.SPEECH_STARTED, payload, "PipecatAudioWorker"))
            
        if type(frame).__name__ == 'TranscriptionFrame':
            self.logger.info("pipecat_transcription_frame_received", extra={"text": frame.text, "is_empty": not bool(frame.text.strip())})
            
            text = frame.text.strip()
            if text:
                import re
                clean_transcription = re.sub(r'[^\w\s]', '', text.lower()).strip()
                clean_spoken = re.sub(r'[^\w\s]', '', self.worker.last_spoken_text).strip()
                time_since_speech = time.time() - self.worker.last_spoken_time
                
                if time_since_speech < (self.worker.mute_gate_delay + 3.0) and clean_spoken:
                    if not getattr(frame, "is_interim", False) and text.strip():
                        try:
                            if text.strip() in self.worker.last_spoken_text:
                                self.logger.warning(f"MUTE GATE CAUGHT SELF-FEEDBACK: '{text}' matched recent TTS output")
                                return
                        except Exception as e:
                            self.logger.error("mute_gate_feedback_check_failed", extra={"error": str(e)}, exc_info=True)

                segment_id = f"pipecat-{uuid.uuid4().hex[:8]}"
                duration = time.perf_counter() - self.segment_start_time
                
                payload = {
                    "segment_id": segment_id,
                    "text": frame.text.strip(),
                    "duration": float(duration),
                    "confidence": 1.0
                }
                
                # PART 2 DIAGNOSTICS: Hallucination vs Echo
                diagnostic_data = {
                    "text": payload["text"],
                    "recent_mic_rms": getattr(self.worker, "recent_mic_rms", 0),
                    "is_tts_playing": self.worker.is_tts_playing,
                    "frame_attrs": dir(frame)
                }
                
                # Extract Whisper confidence metrics if available (varies by Pipecat version)
                for attr in ['confidence', 'avg_logprob', 'no_speech_prob']:
                    if hasattr(frame, attr):
                        diagnostic_data[attr] = getattr(frame, attr)
                
                # Sometimes Pipecat wraps the raw model output in a 'segment' or 'result' attr
                if hasattr(frame, "segment"):
                    if hasattr(frame.segment, "no_speech_prob"):
                        diagnostic_data["no_speech_prob"] = frame.segment.no_speech_prob
                    if hasattr(frame.segment, "avg_logprob"):
                        diagnostic_data["avg_logprob"] = frame.segment.avg_logprob
                
                self.logger.info("pipecat_stt_diagnostic_event", extra=diagnostic_data)
                
                self.logger.info("pipecat_stt_final", extra={"text": payload["text"], "duration": duration})
                
                if payload["text"].strip():
                    self.logger.info("pipecat_publish_attempt", extra={
                        "event": EventType.STT_FINAL_TRANSCRIPT.value,
                        "text_preview": payload["text"][:20]
                    })
                    try:
                        asyncio.create_task(
                            self.event_bus.publish(
                                Event.create(EventType.STT_FINAL_TRANSCRIPT, payload, "PipecatAudioWorker")
                            )
                        )
                        self.logger.info("pipecat_publish_success")
                    except Exception as e:
                        self.logger.error("pipecat_publish_error", extra={"error": str(e)}, exc_info=True)
                
                self.segment_start_time = time.perf_counter()
        
        await super().process_frame(frame, direction)
        await self.push_frame(frame, direction)

class TtsOutputProcessor(FrameProcessor):
    def __init__(self, worker: 'PipecatAudioWorker'):
        super().__init__()
        self.worker = worker
        self.event_bus = worker.event_bus
        self.logger = worker.logger
        self._playback_active = False
        self._last_chunk_time = 0.0
        self._debounce_task = None
        self._completion_task = None
        self._lock = asyncio.Lock()
        self._current_chunk_id = None
        self._active_turn_id = None
        self._stream_ended_turn = None
        self._cancelled_turns: set[str] = set()
        self._turn_start_time = 0.0
        self._current_turn_duration = 0.0
        
        self.event_bus.subscribe(EventType.CONVERSATION_TURN_STARTED, self._handle_turn_started)
        self.event_bus.subscribe(EventType.TTS_AUDIO_CHUNK, self._handle_tts_chunk)
        self.event_bus.subscribe(EventType.TTS_STREAM_END, self._handle_tts_stream_end)
        self.event_bus.subscribe(EventType.TTS_PLAYBACK_CANCELLED, self._handle_tts_cancelled)
        self.event_bus.subscribe(EventType.CONVERSATION_INTERRUPTED, self._handle_interrupted)

    async def cleanup(self) -> None:
        await super().cleanup()
        self.event_bus.unsubscribe(EventType.CONVERSATION_TURN_STARTED, self._handle_turn_started)
        self.event_bus.unsubscribe(EventType.TTS_AUDIO_CHUNK, self._handle_tts_chunk)
        self.event_bus.unsubscribe(EventType.TTS_STREAM_END, self._handle_tts_stream_end)
        self.event_bus.unsubscribe(EventType.TTS_PLAYBACK_CANCELLED, self._handle_tts_cancelled)
        self.event_bus.unsubscribe(EventType.CONVERSATION_INTERRUPTED, self._handle_interrupted)
        if self._debounce_task and not self._debounce_task.done():
            self._debounce_task.cancel()
        if self._completion_task and not self._completion_task.done():
            self._completion_task.cancel()

    async def _handle_turn_started(self, event: Event) -> None:
        turn_id = event.payload.get("turn_id")
        async with self._lock:
            self._active_turn_id = turn_id
            self._current_chunk_id = None
            self._stream_ended_turn = None
            if turn_id and turn_id in self._cancelled_turns:
                self._cancelled_turns.remove(turn_id)

    async def _handle_interrupted(self, event: Event) -> None:
        turn_id = event.payload.get("turn_id")
        async with self._lock:
            if turn_id:
                self._cancelled_turns.add(turn_id)
            self._playback_active = False
            self._active_turn_id = None
            self._stream_ended_turn = None
            if self._debounce_task and not self._debounce_task.done():
                self._debounce_task.cancel()
            if self._completion_task and not self._completion_task.done():
                self._completion_task.cancel()

    async def _handle_tts_chunk(self, event: Event) -> None:
        audio_data = event.payload.get("audio_data")
        sample_rate = event.payload.get("sample_rate", 22050)
        chunk_id = event.payload.get("chunk_id")
        turn_id = event.payload.get("turn_id")
        
        if not audio_data:
            return

        async with self._lock:
            if turn_id and turn_id in self._cancelled_turns:
                return

            self._last_chunk_time = time.time()
            self._current_chunk_id = chunk_id
            if turn_id:
                self._active_turn_id = turn_id
            
            if not self._playback_active:
                self._playback_active = True
                self._turn_start_time = time.perf_counter()
                self._current_turn_duration = 0.0
                
                # DIAGNOSTIC: Log exact time we set the flag synchronously vs event bus
                t_push = time.perf_counter()
                print(f"[DIAGNOSTIC] {t_push:.5f} TtsOutputProcessor: is_tts_playing set to True SYNCHRONOUSLY and frame pushed!")
                self.worker.is_tts_playing = True
                
                self.logger.info("pipecat_firing_tts_playback_started", extra={"chunk_id": chunk_id, "turn_id": turn_id})
                await self.event_bus.publish(
                    Event.create(EventType.TTS_PLAYBACK_STARTED, {"chunk_id": chunk_id, "turn_id": turn_id, "t_push": t_push}, "PipecatAudioWorker")
                )
                if self._debounce_task and not self._debounce_task.done():
                    self._debounce_task.cancel()
                self._debounce_task = asyncio.create_task(self._debounce_loop())
                
            chunk_duration = len(audio_data) / (sample_rate * 2)
            self._current_turn_duration += chunk_duration

        frame = OutputAudioRawFrame(
            audio=audio_data,
            sample_rate=sample_rate,
            num_channels=1
        )
        if getattr(self.worker, "aec_processor", None):
            await self.worker.aec_processor.feed_reference(audio_data, sample_rate)
            
        await self.push_frame(frame)

    async def _handle_tts_stream_end(self, event: Event) -> None:
        turn_id = event.payload.get("turn_id")
        
        async with self._lock:
            # 1. Reject genuinely cancelled turns
            if turn_id and turn_id in self._cancelled_turns:
                self.logger.info("cancelled_tts_stream_end_ignored", extra={"received_turn": turn_id})
                return

            # 2. Reject stale stream ends from past turns
            if turn_id and self._active_turn_id and turn_id != self._active_turn_id:
                self.logger.warning("stale_tts_stream_end_ignored", extra={"received_turn": turn_id, "active_turn": self._active_turn_id})
                return

            # 3. Active playback: complete playback cleanly
            if self._playback_active:
                expected_end_time = self._turn_start_time + self._current_turn_duration
                delay = expected_end_time - time.perf_counter()
                
                if self._completion_task and not self._completion_task.done():
                    self._completion_task.cancel()
                    
                if delay > 0:
                    self.logger.info("tts_stream_end_scheduling_completion", extra={"delay": round(delay, 2), "turn_id": turn_id})
                    self._completion_task = asyncio.create_task(self._delayed_complete_playback(turn_id, delay, "stream_end"))
                else:
                    await self._complete_playback(turn_id, trigger="stream_end")
                return

            # 4. Inactive playback: check if turn was empty (no chunks generated)
            if self._current_chunk_id is None:
                await self._complete_playback(turn_id, trigger="stream_end")
                return

            # Chunks in flight: record pending stream end
            self._stream_ended_turn = turn_id
            self.logger.info("tts_stream_end_recorded_pending_playback", extra={"turn_id": turn_id})

    async def _handle_tts_cancelled(self, event: Event) -> None:
        turn_id = event.payload.get("turn_id")
        async with self._lock:
            if turn_id:
                self._cancelled_turns.add(turn_id)
            self._playback_active = False
            self._active_turn_id = None
            self._stream_ended_turn = None
            if self._debounce_task and not self._debounce_task.done():
                self._debounce_task.cancel()
            if self._completion_task and not self._completion_task.done():
                self._completion_task.cancel()
            self.logger.info("pipecat_tts_cancelled_state_reset")
        print(f"[{time.strftime('%H:%M:%S')}] PIPECAT PIPELINE: push_frame(InterruptionFrame()) called to flush output buffer!")
        await self.push_frame(InterruptionFrame())

    async def _delayed_complete_playback(self, turn_id: str | None, delay: float, trigger: str) -> None:
        try:
            await asyncio.sleep(delay)
            async with self._lock:
                if self._playback_active and self._active_turn_id == turn_id:
                    await self._complete_playback(turn_id, trigger)
        except asyncio.CancelledError:
            pass

    async def _complete_playback(self, turn_id: str | None, trigger: str) -> None:
        self._playback_active = False
        self._stream_ended_turn = None
        if self._debounce_task and not self._debounce_task.done():
            self._debounce_task.cancel()
        if self._completion_task and not self._completion_task.done():
            self._completion_task.cancel()
        
        if hasattr(self.worker, "record_stream_end_fire"):
            self.worker.record_stream_end_fire()
        self.logger.info("pipecat_firing_tts_playback_completed", extra={"trigger": trigger, "turn_id": turn_id})
        await self.event_bus.publish(
            Event.create(EventType.TTS_PLAYBACK_COMPLETED, {"chunk_id": self._current_chunk_id or "end", "turn_id": turn_id}, "PipecatAudioWorker")
        )

    async def _debounce_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(0.1)
                async with self._lock:
                    if not self._playback_active:
                        break
                    # If stream end was recorded for active turn, complete cleanly
                    if self._stream_ended_turn and self._stream_ended_turn == self._active_turn_id:
                        await self._complete_playback(self._active_turn_id, trigger="stream_end")
                        break
                    # Safety net: only fire if we are PAST the physical duration AND 2.5s idle
                    expected_end = self._turn_start_time + self._current_turn_duration
                    time_remaining = expected_end - time.perf_counter()
                    
                    if time_remaining <= 0 and (time.time() - self._last_chunk_time > 2.5):
                        # Don't fire safety net if we're just waiting for a cleanly scheduled completion
                        if self._completion_task and not self._completion_task.done():
                            continue
                            
                        self._playback_active = False
                        self._stream_ended_turn = None
                        if hasattr(self.worker, "record_safety_net_fire"):
                            self.worker.record_safety_net_fire()
                        self.logger.warning(
                            "pipecat_tts_playback_completed_safety_net_triggered",
                            extra={
                                "elapsed": round(time.time() - self._last_chunk_time, 2),
                                "active_turn": self._active_turn_id,
                                "current_chunk": self._current_chunk_id,
                            }
                        )
                        await self.event_bus.publish(
                            Event.create(EventType.TTS_PLAYBACK_COMPLETED, {"chunk_id": self._current_chunk_id or "end", "turn_id": self._active_turn_id}, "PipecatAudioWorker")
                        )
                        break
        except asyncio.CancelledError:
            pass

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        await self.push_frame(frame, direction)

class PipecatAudioWorker(BaseWorker):
    def __init__(self, event_bus: EventBus):
        super().__init__("pipecat_audio", event_bus)
        self.is_tts_playing = False
        self._lock = asyncio.Lock()
        self.last_spoken_text = ""
        self.last_spoken_time = 0.0
        self.tts_processor: TtsOutputProcessor | None = None
        
        # Step 3: Rolling metrics for regression visibility
        self.stream_end_fires: int = 0
        self.safety_net_fires: int = 0
        self._rolling_window: deque[str] = deque(maxlen=20)
        
        settings = load_settings()
        self.mute_gate_delay = getattr(settings, "mute_gate_delay", 0.6)

    def record_stream_end_fire(self) -> None:
        self.stream_end_fires += 1
        self._rolling_window.append("stream_end")
        metrics = getattr(self.event_bus, "metrics", None)
        if metrics and hasattr(metrics, "record_tts_completion"):
            metrics.record_tts_completion("stream_end")

    def record_safety_net_fire(self) -> None:
        self.safety_net_fires += 1
        self._rolling_window.append("safety_net")
        metrics = getattr(self.event_bus, "metrics", None)
        if metrics and hasattr(metrics, "record_tts_completion"):
            metrics.record_tts_completion("safety_net")
        
        # Log CRITICAL if safety net fires on more than 1 in 20 turns in rolling window
        safety_net_count = sum(1 for t in self._rolling_window if t == "safety_net")
        if safety_net_count > 1:
            self.logger.critical(
                "pipecat_safety_net_threshold_exceeded",
                extra={
                    "safety_net_count": safety_net_count,
                    "window_size": len(self._rolling_window),
                    "total_stream_end_fires": self.stream_end_fires,
                    "total_safety_net_fires": self.safety_net_fires,
                }
            )

    async def run(self) -> None:
        if self._debounce_task and not self._debounce_task.done():
            self._debounce_task.cancel()
        if self._completion_task and not self._completion_task.done():
            self._completion_task.cancel()

    async def _handle_turn_started(self, event: Event) -> None:
        turn_id = event.payload.get("turn_id")
        async with self._lock:
            self._active_turn_id = turn_id
            self._current_chunk_id = None
            self._stream_ended_turn = None
            if turn_id and turn_id in self._cancelled_turns:
                self._cancelled_turns.remove(turn_id)

    async def _handle_interrupted(self, event: Event) -> None:
        turn_id = event.payload.get("turn_id")
        async with self._lock:
            if turn_id:
                self._cancelled_turns.add(turn_id)
            self._playback_active = False
            self._active_turn_id = None
            self._stream_ended_turn = None
            if self._debounce_task and not self._debounce_task.done():
                self._debounce_task.cancel()
            if self._completion_task and not self._completion_task.done():
                self._completion_task.cancel()

    async def _handle_tts_chunk(self, event: Event) -> None:
        audio_data = event.payload.get("audio_data")
        sample_rate = event.payload.get("sample_rate", 22050)
        chunk_id = event.payload.get("chunk_id")
        turn_id = event.payload.get("turn_id")
        
        if not audio_data:
            return

        async with self._lock:
            if turn_id and turn_id in self._cancelled_turns:
                return

            self._last_chunk_time = time.time()
            self._current_chunk_id = chunk_id
            if turn_id:
                self._active_turn_id = turn_id
            
            if not self._playback_active:
                self._playback_active = True
                self._turn_start_time = time.perf_counter()
                self._current_turn_duration = 0.0
                self.logger.info("pipecat_firing_tts_playback_started", extra={"chunk_id": chunk_id, "turn_id": turn_id})
                await self.event_bus.publish(
                    Event.create(EventType.TTS_PLAYBACK_STARTED, {"chunk_id": chunk_id, "turn_id": turn_id}, "PipecatAudioWorker")
                )
                if self._debounce_task and not self._debounce_task.done():
                    self._debounce_task.cancel()
                self._debounce_task = asyncio.create_task(self._debounce_loop())
                
            chunk_duration = len(audio_data) / (sample_rate * 2)
            self._current_turn_duration += chunk_duration

        frame = OutputAudioRawFrame(
            audio=audio_data,
            sample_rate=sample_rate,
            num_channels=1
        )
        if getattr(self.worker, "aec_processor", None):
            await self.worker.aec_processor.feed_reference(audio_data, sample_rate)
            
        await self.push_frame(frame)

    async def _handle_tts_stream_end(self, event: Event) -> None:
        turn_id = event.payload.get("turn_id")
        
        async with self._lock:
            # 1. Reject genuinely cancelled turns
            if turn_id and turn_id in self._cancelled_turns:
                self.logger.info("cancelled_tts_stream_end_ignored", extra={"received_turn": turn_id})
                return

            # 2. Reject stale stream ends from past turns
            if turn_id and self._active_turn_id and turn_id != self._active_turn_id:
                self.logger.warning("stale_tts_stream_end_ignored", extra={"received_turn": turn_id, "active_turn": self._active_turn_id})
                return

            # 3. Active playback: complete playback cleanly
            if self._playback_active:
                expected_end_time = self._turn_start_time + self._current_turn_duration
                delay = expected_end_time - time.perf_counter()
                
                if self._completion_task and not self._completion_task.done():
                    self._completion_task.cancel()
                    
                if delay > 0:
                    self.logger.info("tts_stream_end_scheduling_completion", extra={"delay": round(delay, 2), "turn_id": turn_id})
                    self._completion_task = asyncio.create_task(self._delayed_complete_playback(turn_id, delay, "stream_end"))
                else:
                    await self._complete_playback(turn_id, trigger="stream_end")
                return

            # 4. Inactive playback: check if turn was empty (no chunks generated)
            if self._current_chunk_id is None:
                await self._complete_playback(turn_id, trigger="stream_end")
                return

            # Chunks in flight: record pending stream end
            self._stream_ended_turn = turn_id
            self.logger.info("tts_stream_end_recorded_pending_playback", extra={"turn_id": turn_id})

    async def _handle_tts_cancelled(self, event: Event) -> None:
        turn_id = event.payload.get("turn_id")
        async with self._lock:
            if turn_id:
                self._cancelled_turns.add(turn_id)
            self._playback_active = False
            self._active_turn_id = None
            self._stream_ended_turn = None
            if self._debounce_task and not self._debounce_task.done():
                self._debounce_task.cancel()
            if self._completion_task and not self._completion_task.done():
                self._completion_task.cancel()
            self.logger.info("pipecat_tts_cancelled_state_reset")

    async def _delayed_complete_playback(self, turn_id: str | None, delay: float, trigger: str) -> None:
        try:
            await asyncio.sleep(delay)
            async with self._lock:
                if self._playback_active and self._active_turn_id == turn_id:
                    await self._complete_playback(turn_id, trigger)
        except asyncio.CancelledError:
            pass

    async def _complete_playback(self, turn_id: str | None, trigger: str) -> None:
        self._playback_active = False
        self._stream_ended_turn = None
        if self._debounce_task and not self._debounce_task.done():
            self._debounce_task.cancel()
        if self._completion_task and not self._completion_task.done():
            self._completion_task.cancel()
        
        if hasattr(self.worker, "record_stream_end_fire"):
            self.worker.record_stream_end_fire()
        self.logger.info("pipecat_firing_tts_playback_completed", extra={"trigger": trigger, "turn_id": turn_id})
        await self.event_bus.publish(
            Event.create(EventType.TTS_PLAYBACK_COMPLETED, {"chunk_id": self._current_chunk_id or "end", "turn_id": turn_id}, "PipecatAudioWorker")
        )

    async def _debounce_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(0.1)
                async with self._lock:
                    if not self._playback_active:
                        break
                    # If stream end was recorded for active turn, complete cleanly
                    if self._stream_ended_turn and self._stream_ended_turn == self._active_turn_id:
                        await self._complete_playback(self._active_turn_id, trigger="stream_end")
                        break
                    # Safety net only (2.5s idle threshold) in case TTS_STREAM_END is dropped
                    if time.time() - self._last_chunk_time > 2.5:
                        self._playback_active = False
                        self._stream_ended_turn = None
                        if hasattr(self.worker, "record_safety_net_fire"):
                            self.worker.record_safety_net_fire()
                        self.logger.warning(
                            "pipecat_tts_playback_completed_safety_net_triggered",
                            extra={
                                "elapsed": round(time.time() - self._last_chunk_time, 2),
                                "active_turn": self._active_turn_id,
                                "current_chunk": self._current_chunk_id,
                            }
                        )
                        await self.event_bus.publish(
                            Event.create(EventType.TTS_PLAYBACK_COMPLETED, {"chunk_id": self._current_chunk_id or "end", "turn_id": self._active_turn_id}, "PipecatAudioWorker")
                        )
                        break
        except asyncio.CancelledError:
            pass

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        await self.push_frame(frame, direction)

class PipecatAudioWorker(BaseWorker):
    def __init__(self, event_bus: EventBus):
        super().__init__("pipecat_audio", event_bus)
        self.is_tts_playing = False
        self._lock = asyncio.Lock()
        self.last_spoken_text = ""
        self.last_spoken_time = 0.0
        self.tts_processor: TtsOutputProcessor | None = None
        
        # Step 3: Rolling metrics for regression visibility
        self.stream_end_fires: int = 0
        self.safety_net_fires: int = 0
        self._rolling_window: deque[str] = deque(maxlen=20)
        
        settings = load_settings()
        self.mute_gate_delay = getattr(settings, "mute_gate_delay", 0.6)

    def record_stream_end_fire(self) -> None:
        self.stream_end_fires += 1
        self._rolling_window.append("stream_end")
        metrics = getattr(self.event_bus, "metrics", None)
        if metrics and hasattr(metrics, "record_tts_completion"):
            metrics.record_tts_completion("stream_end")

    def record_safety_net_fire(self) -> None:
        self.safety_net_fires += 1
        self._rolling_window.append("safety_net")
        metrics = getattr(self.event_bus, "metrics", None)
        if metrics and hasattr(metrics, "record_tts_completion"):
            metrics.record_tts_completion("safety_net")
        
        # Log CRITICAL if safety net fires on more than 1 in 20 turns in rolling window
        safety_net_count = sum(1 for t in self._rolling_window if t == "safety_net")
        if safety_net_count > 1:
            self.logger.critical(
                "pipecat_safety_net_threshold_exceeded",
                extra={
                    "safety_net_count": safety_net_count,
                    "window_size": len(self._rolling_window),
                    "total_stream_end_fires": self.stream_end_fires,
                    "total_safety_net_fires": self.safety_net_fires,
                }
            )

    async def run(self) -> None:
        self.event_bus.subscribe(EventType.TTS_PLAYBACK_STARTED, self._handle_tts_started)
        self.event_bus.subscribe(EventType.TTS_PLAYBACK_COMPLETED, self._handle_tts_completed)
        self.event_bus.subscribe(EventType.TTS_PLAYBACK_CANCELLED, self._handle_tts_cancelled)
        self.event_bus.subscribe(EventType.RESPONSE_READY, self._handle_response_ready)
        await super().run()

    async def stop(self) -> None:
        if self.tts_processor:
            await self.tts_processor.cleanup()
        if hasattr(self, 'aec_processor'):
            await self.aec_processor.cleanup()
        await super().stop()

    async def _handle_response_ready(self, event: Event) -> None:
        text = event.payload.get("text", "")
        if text:
            async with self._lock:
                self.last_spoken_text = text.lower()
                self.last_spoken_time = time.time()

    async def _handle_tts_started(self, event: Event) -> None:
        async with self._lock:
            # We already set this synchronously now, but we want to measure the delay!
            t_handle = time.perf_counter()
            t_push = event.payload.get("t_push", 0)
            if t_push > 0:
                delta_ms = (t_handle - t_push) * 1000
                print(f"[DIAGNOSTIC] {t_handle:.5f} _handle_tts_started (Event Bus): event received! Race window delta would have been: {delta_ms:.3f} ms")
            self.is_tts_playing = True

    async def _handle_tts_cancelled(self, event: Event) -> None:
        async with self._lock:
            self.is_tts_playing = False
            self.last_spoken_time = time.time()

    async def _handle_tts_completed(self, event: Event) -> None:
        asyncio.create_task(self._delayed_unmute(self.mute_gate_delay))

    async def _delayed_unmute(self, delay: float) -> None:
        await asyncio.sleep(delay)
        async with self._lock:
            self.is_tts_playing = False
            self.last_spoken_time = time.time()

    async def work(self) -> None:
        self.logger.info("pipecat_worker_starting", extra={"detail": "Starting Pipecat Audio Worker"})
        
        output_device = getattr(load_settings(), "audio_output_device", None)
        if isinstance(output_device, str):
            try:
                import pyaudio
                p = pyaudio.PyAudio()
                for i in range(p.get_device_count()):
                    info = p.get_device_info_by_index(i)
                    if output_device.lower() in info.get("name", "").lower() and info.get("maxOutputChannels") > 0:
                        output_device = i
                        break
                p.terminate()
            except ImportError as e:
                self.logger.debug("pyaudio_not_installed_device_selection_skipped", extra={"error": str(e)})
            if isinstance(output_device, str):
                output_device = None

        transport = LocalAudioTransport(
            LocalAudioTransportParams(
                audio_in_enabled=True,
                audio_out_enabled=True,
                output_device_index=output_device,
                audio_out_sample_rate=22050,
                audio_in_sample_rate=16000
            )
        )

        stt = WhisperSTTService(
            device="cpu",
            compute_type="int8",
            settings=WhisperSTTService.Settings(
                model="tiny"
            )
        )

        settings = load_settings()
        vad_stop_secs = getattr(settings, "vad_stop_secs", 0.8)
        aec_delay_ms = getattr(settings, "aec_delay_ms", 180)
        aec_enable_ns = getattr(settings, "aec_enable_ns", False)
        aec_enable_agc = getattr(settings, "aec_enable_agc", False)
        
        self.logger.info("vad_config", extra={"stop_secs": vad_stop_secs})
        vad = SileroVADAnalyzer(params=VADParams(stop_secs=vad_stop_secs))
        vad_processor = VADProcessor(vad_analyzer=vad)

        self.aec_processor = AecProcessor(self, delay_ms=aec_delay_ms, enable_ns=aec_enable_ns, enable_agc=aec_enable_agc)

        self.tts_processor = TtsOutputProcessor(self)
        pipeline = Pipeline([
            transport.input(),
            self.aec_processor,
            MuteGateProcessor(self),
            vad_processor,
            stt,
            TranscriptionPublisher(self),
            self.tts_processor,
            transport.output()
        ])

        task = PipelineTask(pipeline, idle_timeout_secs=None)
        runner = PipelineRunner()
        
        self.logger.info("pipecat_pipeline_ready", extra={"detail": "Pipecat Pipeline defined, starting runner"})
        
        runner_task = asyncio.create_task(runner.run(task))
        
        try:
            while not self.should_stop:
                self.heartbeat("running pipeline")
                done, _ = await asyncio.wait([runner_task], timeout=1.0, return_when=asyncio.FIRST_COMPLETED)
                if runner_task in done:
                    break
                    
            if self.should_stop and not runner_task.done():
                self.logger.info("pipecat_worker_stopping", extra={"detail": "Worker stopping, cancelling Pipecat task"})
                try:
                    await task.cancel()
                except Exception as e:
                    self.logger.error("pipecat_task_cancel_error", extra={"error": str(e)}, exc_info=True)
                try:
                    await asyncio.wait_for(asyncio.shield(runner_task), timeout=2.0)
                except (asyncio.TimeoutError, asyncio.CancelledError):
                    runner_task.cancel()
                    try:
                        await runner_task
                    except asyncio.CancelledError:
                        pass
                    except Exception as e:
                        self.logger.error("pipecat_runner_cancelled_await_error", extra={"error": str(e)}, exc_info=True)
                except Exception as e:
                    self.logger.error("pipecat_runner_shutdown_error", extra={"error": str(e)}, exc_info=True)
                    runner_task.cancel()
                    try:
                        await runner_task
                    except asyncio.CancelledError:
                        pass
                    except Exception as inner_e:
                        self.logger.error("pipecat_runner_cancelled_await_error", extra={"error": str(inner_e)}, exc_info=True)
        finally:
            if self.tts_processor:
                await self.tts_processor.cleanup()
            if getattr(self, "aec_processor", None):
                await self.aec_processor.cleanup()
