import asyncio
import io
import time
from typing import Any
import mss
from PIL import Image
from ..workers.base_worker import BaseWorker
from ..events.bus import EventBus
from ..events.event_types import EventType
from ..events.models import Event
from .vision_validator import VisionValidator


class ScreenCaptureWorker(BaseWorker):
    def __init__(self, event_bus: EventBus, metrics: Any = None):
        super().__init__("screen_capture", event_bus)
        self.metrics = metrics
        self.validator = VisionValidator()
        self._sct = mss.MSS()

    async def run(self) -> None:
        self.event_bus.subscribe(EventType.SCREEN_CAPTURE_REQUESTED, self.handle_capture_request)
        await super().run()

    async def work(self) -> None:
        while not self.should_stop:
            self.heartbeat("capture_ready")
            await asyncio.sleep(2.0)

    async def handle_capture_request(self, event: Event) -> None:
        correlation_id = event.correlation_id
        try:
            # Capture using mss in thread pool
            screenshot = await asyncio.to_thread(self._capture_sync)

            if self.metrics:
                self.metrics.screenshots_captured += 1

            await self.event_bus.publish(Event.create(
                EventType.SCREEN_CAPTURE_COMPLETED,
                {
                    "image_bytes": screenshot["bytes"],
                    "width": screenshot["width"],
                    "height": screenshot["height"],
                    "format": "JPEG",
                    "timestamp": time.time()
                },
                self.name,
                correlation_id
            ))
        except Exception as e:
            self.logger.exception("screen_capture_failed")
            await self.event_bus.publish(Event.create(
                EventType.SCREEN_CAPTURE_FAILED,
                {"error": str(e)},
                self.name,
                correlation_id
            ))

    def _capture_sync(self) -> dict[str, Any]:
        # Capture primary monitor (monitor 1 in mss)
        monitor = self._sct.monitors[1]
        sct_img = self._sct.grab(monitor)

        # Convert to PIL Image
        # MSS returns BGRA, PIL expects RGB for JPEG
        img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")

        # Deterministic resizing to bound context
        if img.width > 2560 or img.height > 1440:
            img.thumbnail((2560, 1440), Image.Resampling.LANCZOS)

        # Compress to JPEG
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", quality=80, optimize=True)

        return {
            "bytes": buffer.getvalue(),
            "width": img.width,
            "height": img.height
        }
