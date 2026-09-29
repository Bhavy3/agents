import asyncio
import queue
import threading
import time
from typing import Any
import numpy as np
import uuid
from core.events.bus import EventBus
from core.events.event_types import EventType
from core.events.models import Event
from core.workers.base_worker import BaseWorker
from core.logging.logger import get_logger

try:
    from piper.voice import PiperVoice  # type: ignore
except ImportError:
    PiperVoice = None


class TtsWorker(BaseWorker):
    """Realtime speech synthesis using Piper."""

    def __init__(
        self,
        event_bus: EventBus,
        model_path: str | None = None,
        config_path: str | None = None,
        max_queue_size: int = 50,
    ) -> None:
        super().__init__("tts", event_bus)
        self.model_path = model_path
        self.config_path = config_path
        self.max_queue_size = max_queue_size
        self.logger = get_logger("audio.tts")

        self.voice = None
        self._is_initialized = False
        self._playback_queue: queue.Queue[bytes] = queue.Queue(maxsize=self.max_queue_size)
        self._publish_task = None

        self._stop_playback = threading.Event()
        self._text_buffer = ""
        self._synthesis_lock = asyncio.Lock()
        
        # Stats
        self.chunks_synthesized = 0
        self.interruptions = 0
        self.synthesis_errors = 0
        self.active_turn_id = None

    async def run(self) -> None:
        # 1. Initialize voice
        if PiperVoice and self.model_path:
            init_success = await asyncio.to_thread(self._initialize_piper)
            if not init_success:
                self.logger.warning("tts_initialization_failed_degraded_mode")
        else:
            self.logger.warning("tts_no_model_or_library_degraded_mode")

        # 2. Subscribe to events
        self.event_bus.subscribe(EventType.ASSISTANT_RESPONSE_PARTIAL, self._handle_partial_response)
        self.event_bus.subscribe(EventType.ASSISTANT_RESPONSE_COMPLETED, self._handle_response_completed)
        self.event_bus.subscribe(EventType.ASSISTANT_RESPONSE_CANCELLED, self._handle_interruption)
        self.event_bus.subscribe(EventType.SPEECH_STARTED, self._handle_interruption)
        self.event_bus.subscribe(EventType.CONVERSATION_INTERRUPTED, self._handle_interruption)
        self.event_bus.subscribe(EventType.CONVERSATION_TURN_STARTED, self._handle_turn_started)

        # 3. Start publish loop
        self._publish_task = asyncio.create_task(self._publish_loop(), name="tts-publish-loop")

        await super().run()

    def _initialize_piper(self) -> bool:
        try:
            import time
            self.voice = PiperVoice.load(self.model_path, self.config_path)
            
            # Warm-up synthesis to force onnxruntime graph optimization during startup
            start_warmup = time.perf_counter()
            list(self.voice.synthesize("warmup"))
            warmup_duration = time.perf_counter() - start_warmup
            
            self._is_initialized = True
            self.logger.info("tts_warmup_complete", extra={"model": self.model_path, "warmup_duration_s": round(warmup_duration, 3)})
            return True
        except Exception as e:
            self.logger.error("tts_load_error", extra={"error": str(e)})
            return False

    async def _handle_turn_started(self, event: Event) -> None:
        self.active_turn_id = event.payload.get("turn_id")
        self._synthesis_lock = asyncio.Lock()
        self._stop_playback.clear()

    async def _handle_partial_response(self, event: Event) -> None:
        turn_id = event.payload.get("turn_id") or self.active_turn_id
        
        # Validate turn context
        if self.active_turn_id and turn_id and turn_id != self.active_turn_id:
            return

        chunk = event.payload.get("text", "")
        if not chunk:
            return

        self._text_buffer += chunk
        
        # Segment by sentences for better prosody
        sentences = []
        while True:
            idx = -1
            for char in (".", "!", "?", "\n", ":"):
                found = self._text_buffer.find(char)
                if found != -1 and (idx == -1 or found < idx):
                    idx = found
            
            if idx != -1:
                sentence = self._text_buffer[:idx+1].strip()
                if sentence:
                    sentences.append(sentence)
                self._text_buffer = self._text_buffer[idx+1:]
            else:
                break
        
        async with self._synthesis_lock:
            for sentence in sentences:
                await self._synthesize_and_queue(sentence, event.correlation_id, turn_id=turn_id)

    async def _handle_response_completed(self, event: Event) -> None:
        turn_id = event.payload.get("turn_id") or self.active_turn_id
        
        async with self._synthesis_lock:
            remaining = self._text_buffer.strip()
            if remaining:
                await self._synthesize_and_queue(remaining, event.correlation_id, turn_id=turn_id)
            self._text_buffer = ""
            
            # Enqueue end of turn marker so _publish_loop emits TTS_STREAM_END
            # only after all audio chunks for this turn are published
            if self._is_initialized and self.voice:
                try:
                    await asyncio.to_thread(self._playback_queue.put, {"type": "end_of_turn", "turn_id": turn_id}, True, 1.0)
                except queue.Full:
                    self.logger.warning("tts_queue_full_dropping_end_marker")

    async def _handle_interruption(self, event: Event) -> None:
        self.logger.info("tts_interruption_received", extra={"turn_id": event.payload.get("turn_id"), "active": self.active_turn_id})
        self._stop_playback.set()
        self._text_buffer = ""
        
        cleared = 0
        while not self._playback_queue.empty():
            try:
                self._playback_queue.get_nowait()
                self._playback_queue.task_done()
                cleared += 1
            except queue.Empty:
                break
        
        if cleared > 0 or self.active_turn_id:
            self.interruptions += 1
            self.logger.info("tts_interrupted_publishing_cancelled", extra={"cleared_chunks": cleared, "turn_id": self.active_turn_id})
            await self.event_bus.publish(
                Event.create(EventType.TTS_PLAYBACK_CANCELLED, {"reason": "interruption", "turn_id": self.active_turn_id}, self.name, event.correlation_id)
            )
            self.active_turn_id = None

    async def _synthesize_and_queue(self, text: str, correlation_id: str | None, turn_id: str | None = None) -> None:
        if not self._is_initialized or not self.voice:
            return

        await self.event_bus.publish(
            Event.create(EventType.TTS_SYNTHESIS_STARTED, {"text": text}, self.name, correlation_id)
        )
        
        try:
            await asyncio.to_thread(self._stream_synthesis, text, correlation_id, turn_id)
        except Exception as e:
            self.synthesis_errors += 1
            self.logger.error("tts_synthesis_failed", extra={"error": str(e)})

    def _stream_synthesis(self, text: str, correlation_id: str | None, turn_id: str | None = None) -> None:
        try:
            for chunk in self.voice.synthesize(text):
                if self._stop_playback.is_set():
                    break
                
                try:
                    target_turn = turn_id or self.active_turn_id
                    item = {"type": "audio", "data": chunk.audio_int16_bytes, "turn_id": target_turn}
                    self._playback_queue.put(item, timeout=1.0)
                    self.chunks_synthesized += 1
                except queue.Full:
                    self.logger.warning("tts_queue_full_dropping_audio")
                    break
        except Exception as e:
            self.logger.error(f"piper_stream_failed: {str(e)}", exc_info=True)

    async def _publish_loop(self) -> None:
        sr = getattr(getattr(self.voice, "config", None), "sample_rate", 22050)
        sample_rate = int(sr) if isinstance(sr, (int, float)) else 22050
        while not self.should_stop:
            try:
                # Use to_thread since queue.Queue is thread-based and blocking
                item = await asyncio.to_thread(self._playback_queue.get, True, 1.0)
                
                if isinstance(item, dict) and item.get("type") == "end_of_turn":
                    end_turn_id = item.get("turn_id") or self.active_turn_id
                    self.logger.info("tts_publishing_stream_end", extra={"turn_id": end_turn_id})
                    await self.event_bus.publish(
                        Event.create(
                            EventType.TTS_STREAM_END,
                            {"turn_id": end_turn_id},
                            self.name
                        )
                    )
                    self._playback_queue.task_done()
                    continue

                chunk = item.get("data")
                turn_id = item.get("turn_id")

                if chunk:
                    chunk_id = str(uuid.uuid4())
                    await self.event_bus.publish(
                        Event.create(
                            EventType.TTS_AUDIO_CHUNK,
                            {"chunk_id": chunk_id, "audio_data": chunk, "sample_rate": sample_rate, "turn_id": turn_id},
                            self.name
                        )
                    )
                self._playback_queue.task_done()
            except queue.Empty:
                pass
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error("tts_publish_loop_error", extra={"error": str(e)})
                await asyncio.sleep(0.1)

    async def stop(self) -> None:
        await super().stop()
        self._stop_playback.set()
        if self._publish_task and not self._publish_task.done():
            self._publish_task.cancel()
            try:
                await self._publish_task
            except asyncio.CancelledError:
                pass

    async def work(self) -> None:
        try:
            while not self.should_stop:
                self.heartbeat(f"tts [chunks={self.chunks_synthesized} interrupts={self.interruptions} errors={self.synthesis_errors}]")
                
                # Watchdog: restart publish task if it died unexpectedly
                if self._publish_task is not None and self._publish_task.done() and not self.should_stop:
                    self.logger.warning("tts_publish_task_dead_restarting")
                    self._stop_playback.clear()
                    self._publish_task = asyncio.create_task(self._publish_loop(), name="tts-publish-loop")
                
                await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            pass
        finally:
            self._stop_playback.set()
