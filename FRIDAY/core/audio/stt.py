import asyncio
import time
import numpy as np
from typing import Any

from core.events.bus import EventBus
from core.events.event_types import EventType
from core.events.models import Event
from core.workers.base_worker import BaseWorker

try:
    from faster_whisper import WhisperModel
except ImportError:
    WhisperModel = None


class SttWorker(BaseWorker):
    """Real-time Speech-to-Text inference worker using Faster-Whisper."""

    def __init__(
        self,
        event_bus: EventBus,
        model_size: str = "tiny.en",
        device: str = "cpu",
        compute_type: str = "int8",
        max_queue_size: int = 10,
    ) -> None:
        super().__init__("stt", event_bus)
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self.max_queue_size = max_queue_size
        
        self.queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=self.max_queue_size)
        self.model: Any = None
        self._is_initialized = False
        self._loop = asyncio.get_event_loop()
        
        # Observability Metrics
        self.transcripts_produced = 0
        self.segments_dropped = 0
        self.total_latency = 0.0

    async def _init_model(self) -> bool:
        """Initialize the inference model safely without blocking."""
        if WhisperModel is None:
            self.logger.warning("stt_degraded_no_library")
            await self.event_bus.publish(
                Event.create(EventType.STT_MODEL_ERROR, {"error": "faster-whisper not installed"}, self.name)
            )
            return False
            
        try:
            self.logger.info("stt_model_initializing", extra={"model": self.model_size})
            self.model = await asyncio.to_thread(
                WhisperModel,
                self.model_size,
                device=self.device,
                compute_type=self.compute_type,
            )
            self._is_initialized = True
            self.logger.info("stt_model_ready")
            return True
        except Exception as e:
            self.logger.error("stt_model_init_failed", extra={"error": str(e)})
            await self.event_bus.publish(
                Event.create(EventType.STT_MODEL_ERROR, {"error": str(e)}, self.name)
            )
            return False

    async def run(self) -> None:
        # Subscribe before starting to catch segments immediately
        self.event_bus.subscribe(EventType.SPEECH_SEGMENT_READY, self._handle_segment)
        await super().run()

    async def _handle_segment(self, event: Event) -> None:
        """Called asynchronously when VAD finishes a speech segment."""
        if not self._is_initialized:
            return
            
        if self.queue.full():
            self.segments_dropped += 1
            await self.event_bus.publish(
                Event.create(
                    EventType.STT_SEGMENT_DROPPED,
                    {"segment_id": event.payload.get("segment_id", "unknown"), "reason": "queue_full"},
                    self.name
                )
            )
            return
            
        await self.queue.put(event.payload)

    def _emit_partial(self, segment_id: str, text: str) -> None:
        """Thread-safe partial transcript emitter."""
        if self.should_stop:
            return
        
        self._loop.call_soon_threadsafe(
            asyncio.create_task,
            self.event_bus.publish(
                Event.create(
                    EventType.STT_PARTIAL_TRANSCRIPT,
                    {"segment_id": segment_id, "text": text},
                    self.name
                )
            )
        )

    def _run_inference(self, audio_array: np.ndarray, segment_id: str) -> tuple[str, float]:
        """Runs blocking inference inside a thread."""
        if self.model is None:
            raise RuntimeError("Model not initialized")
            
        # VAD is handled upstream, so we just transcribe the clean chunk
        segments, info = self.model.transcribe(audio_array, beam_size=1, vad_filter=False)
        
        full_text = ""
        for segment in segments:
            if self.should_stop:
                break
                
            text = segment.text.strip()
            if text:
                full_text += text + " "
                self._emit_partial(segment_id, full_text.strip())
                
        return full_text.strip(), 1.0 # confidence placeholder

    async def work(self) -> None:
        """Main inference loop."""
        if not await self._init_model():
            # Degraded mode
            while not self.should_stop:
                self.heartbeat("stt_degraded")
                await asyncio.sleep(1.0)
            return
            
        try:
            while not self.should_stop:
                self.heartbeat(f"stt_ready [q={self.queue.qsize()} t={self.transcripts_produced} drops={self.segments_dropped}]")
                
                try:
                    payload = await asyncio.wait_for(self.queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                    
                segment_id = payload.get("segment_id", "unknown")
                audio_bytes = payload.get("audio_data", b"")
                duration = payload.get("duration", 0.0)
                
                if not audio_bytes:
                    self.queue.task_done()
                    continue
                
                await self.event_bus.publish(
                    Event.create(EventType.STT_TRANSCRIPTION_STARTED, {"segment_id": segment_id}, self.name)
                )
                
                self.heartbeat(f"stt_inferring [id={segment_id}]")
                start_time = time.perf_counter()
                
                try:
                    # Reconstruct the float32 numpy array from bytes
                    audio_array = np.frombuffer(audio_bytes, dtype=np.float32)
                    
                    # Offload to inference thread to prevent blocking the event loop
                    text, confidence = await asyncio.to_thread(self._run_inference, audio_array, segment_id)
                    
                    if not self.should_stop:
                        latency = time.perf_counter() - start_time
                        self.transcripts_produced += 1
                        self.total_latency += latency
                        
                        await self.event_bus.publish(
                            Event.create(
                                EventType.STT_FINAL_TRANSCRIPT,
                                {
                                    "segment_id": segment_id,
                                    "text": text,
                                    "duration": duration,
                                    "confidence": confidence,
                                },
                                self.name
                            )
                        )
                    else:
                        await self.event_bus.publish(
                            Event.create(
                                EventType.STT_INTERRUPTED,
                                {"segment_id": segment_id, "reason": "worker_stopped"},
                                self.name
                            )
                        )
                        
                except Exception as e:
                    self.logger.error("stt_inference_failed", extra={"error": str(e), "segment_id": segment_id})
                    await self.event_bus.publish(
                        Event.create(EventType.STT_MODEL_ERROR, {"error": str(e)}, self.name)
                    )
                
                self.queue.task_done()
                
        except asyncio.CancelledError:
            pass
        finally:
            # Drain queue if stopped
            while not self.queue.empty():
                try:
                    self.queue.get_nowait()
                    self.queue.task_done()
                except asyncio.QueueEmpty:
                    break
