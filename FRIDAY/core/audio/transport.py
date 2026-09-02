import asyncio
import queue
import time
import threading
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

    Uses InputStream in blocking mode (no callback) with a background thread
    to avoid amplitude attenuation caused by callback mode. Thread-safe queue
    passes chunks to the asyncio event loop in ``work()``.
    """

    def __init__(
        self,
        event_bus: EventBus,
        input_device: int | str | None = None,
        sample_rate: int = 16000,
        channels: int = 1,
        chunk_size: int = 1024,
        max_buffer_chunks: int = 50,  # Bounded buffering
        inactivity_timeout_seconds: float = 5.0,
    ) -> None:
        super().__init__("audio_transport", event_bus)
        self.input_device = input_device
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
        # Thread-safe queue: background audio thread → asyncio event loop
        self._chunk_queue: queue.Queue[tuple[np.ndarray, int, float]] = queue.Queue(maxsize=max_buffer_chunks * 2)
        # Background thread for blocking audio reads
        self._read_thread: threading.Thread | None = None
        self._read_thread_stop = threading.Event()

    async def _start_audio(self) -> bool:
        """Start the audio stream safely."""
        if self._is_running:
            return True

        if sd is None:
            self.logger.warning("audio_transport_degraded_no_library")
            await self._emit_error("sounddevice library not available", None)
            return False

        try:
            # Create InputStream WITHOUT callback - use blocking mode
            self._stream = sd.InputStream(
                samplerate=self.sample_rate,
                channels=self.channels,
                dtype="float32",
                blocksize=self.chunk_size,
                device=self.input_device,
            )
            self._stream.start()
        except Exception as e:
            self.logger.error("audio_transport_init_failed", extra={"error": str(e)}, exc_info=True)
            await self._emit_error(str(e), None)
            return False

        self._is_running = True
        self._start_time = time.perf_counter()
        self._last_chunk_time = self._start_time
        self._total_chunks = 0
        self._buffer.clear()
        self._read_thread_stop.clear()

        actual_device = self.input_device if self.input_device is not None else sd.default.device[0]
        actual_device_name = sd.query_devices(actual_device)['name'] if actual_device is not None else "Unknown"
        
        # Start background thread for blocking reads
        self._read_thread = threading.Thread(
            target=self._blocking_read_loop,
            name="audio_read_thread",
            daemon=True
        )
        self._read_thread.start()
        
        await self.event_bus.publish(
            Event.create(
                EventType.AUDIO_STREAM_STARTED,
                {
                    "device_id": actual_device,
                    "device_name": actual_device_name,
                    "sample_rate": self.sample_rate,
                    "channels": self.channels,
                },
                "audio_transport",
            )
        )
        self.logger.info(f"audio_transport_actual_device device_id={actual_device} name='{actual_device_name}'")
        self.logger.info("audio_transport_started")
        return True

    async def _stop_audio(self, reason: str = "user_requested") -> None:
        """Stop the audio stream immediately."""
        if not self._is_running:
            return

        self._is_running = False
        self._read_thread_stop.set()  # Signal read thread to stop

        if self._stream:
            # Attempt both stop and close independently to maximize cleanup
            stop_error = None
            close_error = None
            
            try:
                self._stream.stop()
            except Exception as e:
                stop_error = str(e)
                self.logger.warning("audio_transport_stop_failed", extra={"error": stop_error})
            
            try:
                self._stream.close()
            except Exception as e:
                close_error = str(e)
                self.logger.error("audio_transport_close_failed", extra={"error": close_error})
            
            if stop_error or close_error:
                self.logger.error(
                    "audio_transport_cleanup_partial",
                    extra={"stop_error": stop_error, "close_error": close_error}
                )
            
            self._stream = None

        # Wait for read thread to finish (with timeout)
        if self._read_thread and self._read_thread.is_alive():
            self._read_thread.join(timeout=2.0)
            if self._read_thread.is_alive():
                self.logger.warning("audio_read_thread_did_not_stop")

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
                    import numpy as np
                    mid_amp = float(np.max(np.abs(chunk_copy)))
                    print(f"FRIDAY DEBUG - MIDPOINT AMP: {mid_amp:.4f}", flush=True)
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
                if self._total_chunks > 0 and now - self._last_chunk_time > self.inactivity_timeout_seconds:
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

    def _blocking_read_loop(self) -> None:
        """Background thread: blocking reads from InputStream, pushes to queue.
        
        This replaces the callback mechanism. Using blocking mode restores
        normal amplitude (0.93x of raw test vs 0.22x with callback).
        """
        while not self._read_thread_stop.is_set():
            try:
                # Blocking read - returns (chunk, overflow) tuple
                result = self._stream.read(self.chunk_size)
                
                # Handle both real and mock stream behaviors
                if isinstance(result, tuple) and len(result) == 2:
                    chunk, overflow = result
                else:
                    # Mock or unexpected format
                    chunk = result if result is not None else None
                    overflow = False
                
                if chunk is not None and not self._read_thread_stop.is_set():
                    chunk_copy = chunk.copy()
                    timestamp = time.perf_counter()
                    
                    import numpy as np
                    try:
                        mid_amp = float(np.max(np.abs(chunk_copy)))
                        print(f"MIDPOINT AMP: {mid_amp:.4f}", flush=True)
                    except Exception as e:
                        print(f"MIDPOINT AMP ERROR: {e}", flush=True)
                    
                    try:
                        self._chunk_queue.put_nowait((chunk_copy, self.chunk_size, timestamp))
                    except queue.Full:
                        # Drop oldest if queue is full — bounded, won't grow
                        try:
                            self._chunk_queue.get_nowait()
                        except queue.Empty:
                            pass
                        try:
                            self._chunk_queue.put_nowait((chunk_copy, self.chunk_size, timestamp))
                        except queue.Full:
                            pass
            except Exception as e:
                if not self._read_thread_stop.is_set():
                    self.logger.error("audio_read_loop_error", extra={"error": str(e)}, exc_info=True)
                break

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

