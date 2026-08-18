import asyncio
import queue
import time
import numpy as np
from collections import deque
from typing import Any

from core.events.bus import EventBus
from core.events.event_types import EventType
from core.events.models import Event, EventPriority
from core.logging.logger import get_logger

from core.workers.base_worker import BaseWorker

try:
    import sounddevice as sd
except Exception:
    sd = None  # Handle degraded mode if sounddevice fails to load


class AudioTransportWorker(BaseWorker):
    """Isolated audio hardware transport layer.

    The sounddevice callback runs on an OS thread.  We push raw chunk data
    into a ``queue.Queue`` (thread-safe) and drain it from the asyncio
    event loop in ``work()``, keeping Event construction on the loop thread.
    """

    def __init__(
        self,
        event_bus: EventBus,
        sample_rate: int = 16000,
        channels: int = 1,
        chunk_size: int = 1024,
        max_buffer_chunks: int = 50,  # Bounded buffering
        inactivity_timeout_seconds: float = 5.0,
    ) -> None:
        super().__init__("audio_transport", event_bus)
        self.sample_rate = sample_rate
        self.channels = channels
        self.chunk_size = chunk_size
        self.max_buffer_chunks = max_buffer_chunks
        self.inactivity_timeout_seconds = inactivity_timeout_seconds

        self._stream: Any = None
        self._buffer: deque[np.ndarray] = deque(maxlen=max_buffer_chunks)
        self._is_running = False
        self._last_chunk_time = 0.0
        self._start_time = 0.0
        self._total_chunks = 0
        self._last_overflow_log = 0.0
        # Thread-safe queue: OS audio thread → asyncio event loop
        self._chunk_queue: queue.Queue[tuple[np.ndarray, int, float]] = queue.Queue(maxsize=max_buffer_chunks * 2)

    async def _start_audio(self) -> bool:
        """Start the audio stream safely."""
        if self._is_running:
            return True

        if sd is None:
            self.logger.warning("audio_transport_degraded_no_library")
            await self._emit_error("sounddevice library not available", None)
            return False

        try:
            self._stream = sd.InputStream(
                samplerate=self.sample_rate,
                channels=self.channels,
                dtype="float32",
                blocksize=self.chunk_size,
                callback=self._audio_callback,
            )
            self._stream.start()
        except Exception as e:
            self.logger.error("audio_transport_init_failed", extra={"error": str(e)})
            await self._emit_error(str(e), None)
            return False

        self._is_running = True
        self._start_time = time.perf_counter()
        self._last_chunk_time = self._start_time
        self._total_chunks = 0
        self._buffer.clear()

        await self.event_bus.publish(
            Event.create(
                EventType.AUDIO_STREAM_STARTED,
                {
                    "device_id": None,
                    "sample_rate": self.sample_rate,
                    "channels": self.channels,
                },
                "audio_transport",
            )
        )
        self.logger.info("audio_transport_started")
        return True

    async def _stop_audio(self, reason: str = "user_requested") -> None:
        """Stop the audio stream immediately."""
        if not self._is_running:
            return

        self._is_running = False

        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception as e:
                self.logger.error("audio_transport_close_error", extra={"error": str(e)})
            self._stream = None

        duration = time.perf_counter() - self._start_time
        await self.event_bus.publish(
            Event.create(
                EventType.AUDIO_STREAM_STOPPED,
                {
                    "reason": reason,
                    "duration": round(duration, 3),
                    "total_chunks": self._total_chunks,
                },
                "audio_transport",
            )
        )
        self.logger.info("audio_transport_stopped", extra={"reason": reason})

    async def work(self) -> None:
        """Background task: drain the thread-safe queue, publish events, check timeouts."""
        if not await self._start_audio():
            return
            
        try:
            while not self.should_stop:
                self.heartbeat(f"audio_streaming [buffer={len(self._buffer)}/{self.max_buffer_chunks} chunks={self._total_chunks}]")

                # Drain all available chunks from the thread-safe queue
                drained = 0
                while drained < self.max_buffer_chunks:
                    try:
                        chunk_copy, frames, timestamp = self._chunk_queue.get_nowait()
                    except queue.Empty:
                        break
                    drained += 1
                    self._buffer.append(chunk_copy)
                    self._last_chunk_time = timestamp
                    self._total_chunks += 1
                    amplitude = float(np.max(np.abs(chunk_copy)))

                    # Backpressure: skip publishing if EventBus is saturated
                    if self.event_bus.queue_utilization > 0.9:
                        continue

                    await self.event_bus.publish(
                        Event.create(
                            EventType.AUDIO_CHUNK_RECEIVED,
                            {
                                "chunk_size": frames,
                                "timestamp": timestamp,
                                "amplitude": amplitude,
                                "data": chunk_copy.tobytes(),
                            },
                            "audio_transport",
                        )
                    )

                await asyncio.sleep(0.05)  # ~20 Hz drain cycle

                # Inactivity timeout
                now = time.perf_counter()
                if self._last_chunk_time > 0 and now - self._last_chunk_time > self.inactivity_timeout_seconds:
                    self.logger.warning("audio_transport_timeout")
                    await self.event_bus.publish(
                        Event.create(
                            EventType.AUDIO_STREAM_TIMEOUT,
                            {"timeout_type": "inactivity"},
                            "audio_transport"
                        )
                    )
                    await self._stop_audio(reason="timeout")
                    break
        except asyncio.CancelledError:
            pass
        finally:
            await self._stop_audio(reason="interrupted" if self.should_stop else "finished")

    def _audio_callback(self, indata: np.ndarray, frames: int, time_info: Any, status: Any) -> None:
        """Called by sounddevice OS thread. Must NOT block.

        Only touches the thread-safe ``_chunk_queue`` — no Event construction,
        no asyncio calls, no datetime/uuid operations on this thread.
        """
        if not self._is_running:
            return

        chunk_copy = indata.copy()
        timestamp = time.perf_counter()

        try:
            self._chunk_queue.put_nowait((chunk_copy, frames, timestamp))
        except queue.Full:
            # Drop oldest if queue is full — bounded, won't grow
            try:
                self._chunk_queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._chunk_queue.put_nowait((chunk_copy, frames, timestamp))
            except queue.Full:
                pass

    async def _emit_error(self, error: str, device_id: Any) -> None:
        await self.event_bus.publish(
            Event.create(
                EventType.AUDIO_DEVICE_ERROR,
                {"error": error, "device_id": device_id},
                "audio_transport",
            )
        )

    def read_buffer(self) -> list[np.ndarray]:
        chunks = list(self._buffer)
        self._buffer.clear()
        return chunks

