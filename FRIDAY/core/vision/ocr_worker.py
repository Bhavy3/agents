import asyncio
import io
import time
from typing import Any
import pytesseract
from PIL import Image
from ..workers.base_worker import BaseWorker
from ..events.bus import EventBus
from ..events.event_types import EventType
from ..events.models import Event
from .vision_validator import VisionValidator


class OCRWorker(BaseWorker):
    def __init__(self, event_bus: EventBus, metrics: Any = None):
        super().__init__("ocr_worker", event_bus)
        self.metrics = metrics
        self.validator = VisionValidator()
        self._tesseract_available = None

    async def run(self) -> None:
        self.event_bus.subscribe(EventType.OCR_REQUESTED, self.handle_ocr_request)
        await super().run()

    async def work(self) -> None:
        while not self.should_stop:
            # Lazy health check for tesseract binary
            if self._tesseract_available is None:
                self._tesseract_available = await self._check_tesseract()
                if not self._tesseract_available:
                    self.logger.warning("tesseract_not_found_vision_degraded")
                    await self.event_bus.publish(Event.create(
                        EventType.VISION_DEGRADED_MODE,
                        {"reason": "tesseract_missing", "component": "ocr"},
                        self.name
                    ))
                    if self.metrics:
                        self.metrics.vision_degraded_mode = True

            self.heartbeat(f"ocr_active [available={self._tesseract_available}]")
            await asyncio.sleep(5.0)

    async def _check_tesseract(self) -> bool:
        try:
            # Try to get version to confirm binary existence
            await asyncio.to_thread(pytesseract.get_tesseract_version)
            return True
        except Exception:
            return False

    async def handle_ocr_request(self, event: Event) -> None:
        correlation_id = event.correlation_id
        if self._tesseract_available is False:
            await self.event_bus.publish(Event.create(
                EventType.OCR_FAILED,
                {"error": "tesseract_binary_not_found_on_system"},
                self.name,
                correlation_id
            ))
            return

        image_bytes = event.payload.get("image_bytes")
        if not image_bytes:
            await self.event_bus.publish(Event.create(
                EventType.OCR_FAILED,
                {"error": "no_image_data_provided"},
                self.name,
                correlation_id
            ))
            return

        try:
            start_time = time.time()
            # Run OCR in thread pool to avoid blocking event loop
            text = await asyncio.wait_for(
                asyncio.to_thread(self._ocr_sync, image_bytes),
                timeout=5.0
            )
            latency = (time.time() - start_time) * 1000

            # Sanitize and truncate
            clean_text = self.validator.sanitize_ocr(text)
            if len(clean_text) > 5000:
                clean_text = clean_text[:5000] + "... [TRUNCATED]"

            if self.metrics:
                self.metrics.ocr_requests += 1
                # Update rolling average latency
                m = self.metrics
                m.average_ocr_latency_ms = (m.average_ocr_latency_ms * 0.9) + (latency * 0.1)

            await self.event_bus.publish(Event.create(
                EventType.OCR_COMPLETED,
                {"text": clean_text, "latency_ms": latency},
                self.name,
                correlation_id
            ))
        except asyncio.TimeoutError:
            self.logger.error("ocr_timeout_exceeded")
            if self.metrics:
                self.metrics.ocr_failures += 1
            await self.event_bus.publish(Event.create(
                EventType.OCR_FAILED,
                {"error": "timeout"},
                self.name,
                correlation_id
            ))
        except Exception as e:
            self.logger.exception("ocr_execution_failed")
            if self.metrics:
                self.metrics.ocr_failures += 1
            await self.event_bus.publish(Event.create(
                EventType.OCR_FAILED,
                {"error": str(e)},
                self.name,
                correlation_id
            ))

    def _ocr_sync(self, image_bytes: bytes) -> str:
        with Image.open(io.BytesIO(image_bytes)) as img:
            return pytesseract.image_to_string(img)
