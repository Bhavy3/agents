import asyncio
import time
import uuid

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
    ) -> None:
        super().__init__("vad", event_bus)
        self.silence_threshold = silence_threshold
        self.min_speech_duration = min_speech_duration
        self.max_speech_duration = max_speech_duration
        self.speech_inactivity_timeout = speech_inactivity_timeout

        self._lock = asyncio.Lock()
        self._is_speaking = False
        self._speech_start_time = 0.0
        self._last_speech_time = 0.0
        self._current_segment_chunks: list[bytes] = []
        self._current_segment_id: str | None = None
        self._max_amplitude = 0.0
        
        # Stats
        self.segments_produced = 0
        self.noise_rejected = 0

    async def run(self) -> None:
        # Override run to set up subscription
        self.event_bus.subscribe(EventType.AUDIO_CHUNK_RECEIVED, self._handle_audio_chunk)
        await super().run()

    async def _handle_audio_chunk(self, event: Event) -> None:
        amplitude = event.payload.get("amplitude", 0.0)
        timestamp = event.payload.get("timestamp", time.perf_counter())
        data = event.payload.get("data", b"")

        async with self._lock:
            if amplitude > self.silence_threshold:
                if not self._is_speaking:
                    self._is_speaking = True
                    self._speech_start_time = timestamp
                    self._last_speech_time = timestamp
                    self._current_segment_id = str(uuid.uuid4())[:8]
                    self._current_segment_chunks = [data]
                    self._max_amplitude = amplitude
                    
                    await self.event_bus.publish(
                        Event.create(
                            EventType.SPEECH_STARTED,
                            {"timestamp": timestamp, "amplitude": amplitude},
                            self.name
                        )
                    )
                else:
                    self._last_speech_time = timestamp
                    self._current_segment_chunks.append(data)
                    self._max_amplitude = max(self._max_amplitude, amplitude)
            else:
                if self._is_speaking:
                    self._current_segment_chunks.append(data)
                    
                    if timestamp - self._last_speech_time > self.speech_inactivity_timeout:
                        await self._finalize_segment(timestamp, "inactivity")

    async def _finalize_segment(self, end_timestamp: float, reason: str) -> None:
        """Must be called with lock held."""
        if not self._is_speaking:
            return

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
        self._is_speaking = False
        self._speech_start_time = 0.0
        self._last_speech_time = 0.0
        self._current_segment_chunks.clear()
        self._current_segment_id = None
        self._max_amplitude = 0.0

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
