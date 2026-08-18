import asyncio
import queue
import threading
import time
from typing import Any
import numpy as np
try:
    import sounddevice as sd
except ImportError:
    sd = None
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
        self._playback_thread = None

        self._stop_playback = threading.Event()
        self._text_buffer = ""
        
        # Stats
        self.chunks_synthesized = 0
        self.interruptions = 0
        self.synthesis_errors = 0
        self.playback_active = False

    async def run(self) -> None:
        # 1. Initialize voice
        if PiperVoice and self.model_path:
            init_success = await asyncio.to_thread(self._initialize_piper)
            if not init_success:
                self.logger.warning("tts_initialization_failed_degraded_mode")
        else:
            self.logger.warning("tts_no_model_or_library_degraded_mode")

        if sd is None:
            self.logger.error("sounddevice_not_installed_tts_disabled")
            return

        # 2. Subscribe to events
        self.event_bus.subscribe(EventType.ASSISTANT_RESPONSE_PARTIAL, self._handle_partial_response)
        self.event_bus.subscribe(EventType.ASSISTANT_RESPONSE_COMPLETED, self._handle_response_completed)
        self.event_bus.subscribe(EventType.ASSISTANT_RESPONSE_CANCELLED, self._handle_interruption)
        self.event_bus.subscribe(EventType.SPEECH_STARTED, self._handle_interruption)
        self.event_bus.subscribe(EventType.CONVERSATION_INTERRUPTED, self._handle_interruption)

        # 3. Start playback thread
        self._playback_thread = threading.Thread(target=self._playback_loop, daemon=True)
        self._playback_thread.start()

        await super().run()

    def _initialize_piper(self) -> bool:
        try:
            self.voice = PiperVoice.load(self.model_path, self.config_path)
            self._is_initialized = True
            self.logger.info("tts_initialized", extra={"model": self.model_path})
            return True
        except Exception as e:
            self.logger.error("tts_load_error", extra={"error": str(e)})
            return False

    async def _handle_partial_response(self, event: Event) -> None:
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
        
        for sentence in sentences:
            await self._synthesize_and_queue(sentence, event.correlation_id)

    async def _handle_response_completed(self, event: Event) -> None:
        remaining = self._text_buffer.strip()
        if remaining:
            await self._synthesize_and_queue(remaining, event.correlation_id)
        self._text_buffer = ""

    async def _handle_interruption(self, event: Event) -> None:
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
        
        if cleared > 0 or self.playback_active:
            self.interruptions += 1
            self.logger.info("tts_interrupted", extra={"cleared_chunks": cleared})
            await self.event_bus.publish(
                Event.create(EventType.TTS_PLAYBACK_CANCELLED, {"reason": "interruption"}, self.name, event.correlation_id)
            )

    async def _synthesize_and_queue(self, text: str, correlation_id: str | None) -> None:
        if not self._is_initialized or not self.voice:
            return

        await self.event_bus.publish(
            Event.create(EventType.TTS_SYNTHESIS_STARTED, {"text": text}, self.name, correlation_id)
        )
        
        try:
            await asyncio.to_thread(self._stream_synthesis, text, correlation_id)
        except Exception as e:
            self.synthesis_errors += 1
            self.logger.error("tts_synthesis_failed", extra={"error": str(e)})

    def _stream_synthesis(self, text: str, correlation_id: str | None) -> None:
        try:
            for chunk in self.voice.synthesize(text):
                if self._stop_playback.is_set():
                    break
                
                try:
                    self._playback_queue.put(chunk.audio_data, timeout=1.0)
                    self.chunks_synthesized += 1
                except queue.Full:
                    self.logger.warning("tts_queue_full_dropping_audio")
                    break
        except Exception as e:
            self.logger.error("piper_stream_failed", extra={"error": str(e)})

    def _playback_loop(self) -> None:
        sample_rate = 22050
        
        try:
            # Using sounddevice RawOutputStream for byte-based playback
            with sd.RawOutputStream(samplerate=sample_rate, blocksize=1024, channels=1, dtype='int16') as stream:
                while not self.should_stop:
                    try:
                        audio_data = self._playback_queue.get(timeout=0.1)
                    except queue.Empty:
                        self.playback_active = False
                        continue
                    
                    self.playback_active = True
                    self._stop_playback.clear()
                    
                    # Write in 1024-sample blocks (2048 bytes for int16)
                    block_bytes = 1024 * 2
                    for i in range(0, len(audio_data), block_bytes):
                        if self._stop_playback.is_set():
                            break
                        
                        chunk = audio_data[i:i+block_bytes]
                        if len(chunk) < block_bytes:
                            chunk = chunk + b'\x00' * (block_bytes - len(chunk))
                        
                        stream.write(chunk)
                    
                    self._playback_queue.task_done()
        except Exception as e:
            self.logger.error("tts_playback_failed", extra={"error": str(e)})

    async def work(self) -> None:
        try:
            while not self.should_stop:
                self.heartbeat(f"tts [chunks={self.chunks_synthesized} interrupts={self.interruptions} errors={self.synthesis_errors}]")
                
                # Watchdog: restart playback thread if it died unexpectedly
                if self._playback_thread is not None and not self._playback_thread.is_alive() and not self.should_stop:
                    if sd is not None:
                        self.logger.warning("tts_playback_thread_dead_restarting")
                        self._stop_playback.clear()
                        self._playback_thread = threading.Thread(target=self._playback_loop, daemon=True)
                        self._playback_thread.start()
                
                await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            pass
        finally:
            self._stop_playback.set()
