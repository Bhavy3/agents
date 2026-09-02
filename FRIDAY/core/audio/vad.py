import asyncio
import time
import uuid
import os
import urllib.request
import urllib.error
import socket
from collections import deque
import numpy as np

from core.events.bus import EventBus
from core.events.event_types import EventType
from core.events.models import Event, EventPriority
from core.workers.base_worker import BaseWorker


class VadWorker(BaseWorker):
    """Voice Activity Detection worker. Processes audio chunks to detect speech boundaries."""

    def __init__(
        self,
        event_bus: EventBus,
        silence_threshold: float = 0.01,
        min_speech_duration: float = 0.5,
        max_speech_duration: float = 30.0,
        speech_inactivity_timeout: float = 1.5,
        activation_chunks: int = 1, # Need this many speech chunks to start
        cooldown_seconds: float = 0.8, # Wait before starting new segment
    ) -> None:
        super().__init__("vad", event_bus)
        self.silence_threshold = silence_threshold
        self.min_speech_duration = min_speech_duration
        self.max_speech_duration = max_speech_duration
        self.speech_inactivity_timeout = speech_inactivity_timeout
        self.activation_chunks = activation_chunks
        self.cooldown_seconds = cooldown_seconds

    
        self._lock = asyncio.Lock()
        self._is_speaking = False
        self._speech_start_time = 0.0
        self._last_speech_time = 0.0
        self._current_segment_chunks: list[bytes] = []
        self._current_segment_id: str | None = None
        self._max_amplitude = 0.0
        self._noise_floor = silence_threshold
        self._is_tts_playing = False
        
        # Debouncing
        self._speech_chunk_counter = 0
        self._cooldown_until = 0.0
        self._pre_speech_buffer: list[bytes] = [] # To avoid losing first chunks during activation
        
        # Stats
        self.segments_produced = 0
        self.noise_rejected = 0
        
        # Silero VAD
        self.model_path = os.path.join("data", "models", "vad", "silero_vad.onnx")
        self._ort_session = None
        self._state = None
        self._latencies: deque[float] = deque(maxlen=100)  # Bounded latency tracking
        self._setup_silero()

    def _setup_silero(self):
        try:
            import onnxruntime as ort
            os.makedirs(os.path.dirname(self.model_path), exist_ok=True)
            if not os.path.exists(self.model_path):
                self.logger.info("Downloading Silero VAD ONNX model...")
                url = "https://raw.githubusercontent.com/snakers4/silero-vad/master/src/silero_vad/data/silero_vad.onnx"
                try:
                    # Add timeout to prevent indefinite hangs
                    socket.setdefaulttimeout(30)  # 30 second timeout
                    urllib.request.urlretrieve(url, self.model_path)
                except (socket.timeout, urllib.error.URLError, urllib.error.HTTPError) as e:
                    self.logger.error("silero_vad_download_timeout", extra={"error": str(e), "url": url})
                    # Fall back to degraded mode - VAD will use amplitude threshold
                    return
                finally:
                    socket.setdefaulttimeout(None)  # Reset timeout
            self._ort_session = ort.InferenceSession(self.model_path)
            self._state = np.zeros((2, 1, 128), dtype=np.float32)
            self.logger.info("silero_vad_initialized")
        except Exception as e:
            self.logger.error("Failed to setup Silero VAD", extra={"error": str(e)}, exc_info=True)

    async def run(self) -> None:
        # Override run to set up subscription
        self.event_bus.subscribe(EventType.AUDIO_CHUNK_RECEIVED, self._handle_audio_chunk)
        self.event_bus.subscribe(EventType.AUDIO_CHUNK, self._handle_audio_chunk)
        self.event_bus.subscribe(EventType.TTS_PLAYBACK_STARTED, self._handle_tts_playback_started)
        self.event_bus.subscribe(EventType.TTS_PLAYBACK_COMPLETED, self._handle_tts_playback_completed)
        await super().run()

    async def _handle_tts_playback_started(self, event: Event) -> None:
        async with self._lock:
            self._is_tts_playing = True

    async def _handle_tts_playback_completed(self, event: Event) -> None:
        async with self._lock:
            self._is_tts_playing = False

    async def _handle_audio_chunk(self, event: Event) -> None:
        amplitude = event.payload.get("amplitude", 0.0)
        timestamp = event.payload.get("timestamp", time.perf_counter())
        data = event.payload.get("data", event.payload.get("audio_data", b""))

        async with self._lock:
            self.logger.info(f"AUDIO_CHUNK_RECEIVED amplitude={amplitude:.4f}")
            if self._is_tts_playing:
                return
            now = timestamp
            if now < self._cooldown_until:
                return

            is_speech = False
            if self._ort_session is not None:
                try:
                    chunk_data = np.frombuffer(data, dtype=np.float32).copy()
                    
                    # NORMALIZATION FIX:
                    # The audio stream is correctly float32 [-1.0, 1.0], but the hardware mic 
                    # captures at a very low baseline (~0.05 peak). Silero VAD is trained on
                    # normalized speech and perceives 0.05 as silence/noise (0.0015 prob).
                    # We apply a static software gain to scale it up, preserving the envelope,
                    # and clip to prevent distortion.
                    chunk_data = np.clip(chunk_data * 15.0, -1.0, 1.0)
                    
                    sr = np.array(16000, dtype=np.int64)
                    
                    probs = []
                    latencies = []
                    for i in range(0, len(chunk_data), 512):
                        sub_chunk = chunk_data[i:i+512]
                        if len(sub_chunk) < 512:
                            sub_chunk = np.pad(sub_chunk, (0, 512 - len(sub_chunk)))
                        
                        inputs = {
                            'input': sub_chunk.reshape(1, -1),
                            'sr': sr,
                            'state': self._state
                        }
                        
                        start_t = time.perf_counter()
                        out, self._state = self._ort_session.run(None, inputs)
                        latencies.append(time.perf_counter() - start_t)
                        probs.append(float(out[0][0]))
                        
                    latency = sum(latencies)
                    self._latencies.append(latency)
                    if len(self._latencies) == 100:
                        avg_ms = (sum(self._latencies) / 100) * 1000
                        self.logger.info(f"silero_vad_latency_measured avg_ms={avg_ms:.2f}")

                    prob = max(probs) if probs else 0.0
                    self.logger.info(f"VAD_PROBABILITY score={prob:.4f} amplitude={amplitude:.4f}")
                    is_speech = prob > 0.5
                except Exception as e:
                    self.logger.error("silero_vad_inference_failed", extra={"error": str(e)})
                    is_speech = amplitude > self.silence_threshold
            else:
                is_speech = amplitude > self.silence_threshold

            if is_speech:
                if not self._is_speaking:
                    self._speech_chunk_counter += 1
                    self._pre_speech_buffer.append(data)
                    
                    if self._speech_chunk_counter >= self.activation_chunks:
                        self._is_speaking = True
                        self._speech_start_time = now - (self.activation_chunks * 0.05) # Backdate slightly
                        self._last_speech_time = now
                        self._current_segment_id = str(uuid.uuid4())[:8]
                        self._current_segment_chunks = list(self._pre_speech_buffer)
                        self._max_amplitude = amplitude
                        self._pre_speech_buffer.clear()
                        
                        self.logger.info(f"SPEECH_STARTED segment_id={self._current_segment_id} amplitude={amplitude:.4f}")
                        await self.event_bus.publish(
                            Event.create(
                                EventType.SPEECH_STARTED,
                                {"timestamp": now, "amplitude": amplitude, "segment_id": self._current_segment_id},
                                self.name
                            )
                        )
                else:
                    self._last_speech_time = now
                    self._current_segment_chunks.append(data)
                    self._max_amplitude = max(self._max_amplitude, amplitude)
            else:
                if not self._is_speaking:
                    self._speech_chunk_counter = max(0, self._speech_chunk_counter - 1)
                    if self._pre_speech_buffer:
                        self._pre_speech_buffer.pop(0) if len(self._pre_speech_buffer) > 5 else None
                else:
                    self._current_segment_chunks.append(data)
                    
                    if now - self._last_speech_time > self.speech_inactivity_timeout:
                        await self._finalize_segment(now, "inactivity")

    async def _finalize_segment(self, end_timestamp: float, reason: str) -> None:
        """Must be called with lock held."""
        if not self._is_speaking:
            return

        self._cooldown_until = end_timestamp + self.cooldown_seconds
        duration = end_timestamp - self._speech_start_time
        
        if duration < self.min_speech_duration:
            self.noise_rejected += 1
            await self.event_bus.publish(
                Event.create(
                    EventType.SPEECH_NOISE_REJECTED,
                    {"duration": round(duration, 3), "max_amplitude": self._max_amplitude, "reason": "too_short"},
                    self.name
                )
            )
        else:
            self.segments_produced += 1
            self.logger.info(f"SPEECH_SEGMENT_READY segment_id={self._current_segment_id} duration={duration:.3f}")
            await self.event_bus.publish(
                Event.create(
                    EventType.SPEECH_ENDED,
                    {"timestamp": end_timestamp, "duration": round(duration, 3)},
                    self.name
                )
            )
            
            audio_data = b"".join(self._current_segment_chunks)
            await self.event_bus.publish(
                Event.create(
                    EventType.SPEECH_SEGMENT_READY,
                    {
                        "duration": round(duration, 3),
                        "chunk_count": len(self._current_segment_chunks),
                        "segment_id": self._current_segment_id,
                        "audio_data": audio_data,
                    },
                    self.name
                )
            )

        self._reset_state()

    def _reset_state(self) -> None:
        if self._ort_session is not None:
            self._state = np.zeros((2, 1, 128), dtype=np.float32)
        self._is_speaking = False
        self._speech_start_time = 0.0
        self._last_speech_time = 0.0
        self._current_segment_chunks.clear()
        self._current_segment_id = None
        self._max_amplitude = 0.0
        self._speech_chunk_counter = 0
        self._pre_speech_buffer.clear()

    async def work(self) -> None:
        try:
            while not self.should_stop:
                self.heartbeat(f"vad [segments={self.segments_produced} noise={self.noise_rejected}]")
                await asyncio.sleep(0.5)
                
                async with self._lock:
                    if self._is_speaking:
                        now = time.perf_counter()
                        # Check max segment timeout
                        if now - self._speech_start_time > self.max_speech_duration:
                            await self.event_bus.publish(
                                Event.create(
                                    EventType.SPEECH_TIMEOUT,
                                    {"reason": "max_duration_exceeded", "duration": round(now - self._speech_start_time, 3)},
                                    self.name
                                )
                            )
                            await self._finalize_segment(now, "timeout")
        except asyncio.CancelledError:
            pass
        finally:
            async with self._lock:
                if self._is_speaking:
                    await self.event_bus.publish(
                        Event.create(
                            EventType.SPEECH_INTERRUPTED,
                            {"reason": "worker_stopped", "segment_id": self._current_segment_id},
                            self.name
                        )
                    )
                    self._reset_state()
