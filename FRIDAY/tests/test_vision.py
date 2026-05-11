import asyncio
import pytest
import io
from PIL import Image
from core.events.bus import EventBus
from core.events.event_types import EventType
from core.events.models import Event
from core.vision.screen_capture import ScreenCaptureWorker
from core.vision.ocr_worker import OCRWorker
from core.vision.vision_validator import VisionValidator


@pytest.mark.asyncio
async def test_screen_capture_emits_valid_image():
    bus = EventBus()
    worker = ScreenCaptureWorker(bus)
    await bus.start()
    await worker.start()
    await asyncio.sleep(0.1)

    results = []

    async def on_completed(event):
        results.append(event.payload)

    bus.subscribe(EventType.SCREEN_CAPTURE_COMPLETED, on_completed)

    await bus.publish(Event.create(EventType.SCREEN_CAPTURE_REQUESTED, {}, "test"))

    # Capture can take a moment
    for _ in range(10):
        if len(results) > 0:
            break
        await asyncio.sleep(0.2)

    assert len(results) == 1
    assert "image_bytes" in results[0]
    assert results[0]["width"] > 0
    assert results[0]["format"] == "JPEG"

    # Verify it's a real image
    img = Image.open(io.BytesIO(results[0]["image_bytes"]))
    assert img.size == (results[0]["width"], results[0]["height"])

    await worker.stop()
    await bus.stop()


@pytest.mark.asyncio
async def test_ocr_validator_sanitization():
    validator = VisionValidator()
    raw_text = "My OpenAI key is sk-123456789012345678901234567890123456789012345678 and some other text."
    sanitized = validator.sanitize_ocr(raw_text)
    assert "[REDACTED_OPENAI_KEY]" in sanitized
    assert "sk-" not in sanitized
    
    # Test whitespace normalization
    raw_text = "Line 1\n\nLine 2    Line 3"
    sanitized = validator.sanitize_ocr(raw_text)
    assert sanitized == "Line 1 Line 2 Line 3"


@pytest.mark.asyncio
async def test_vision_degraded_mode_on_missing_tesseract():
    # In this environment, we confirmed tesseract is missing
    bus = EventBus()
    worker = OCRWorker(bus)
    
    degraded_events = []
    async def on_degraded(event):
        degraded_events.append(event.payload)
        
    bus.subscribe(EventType.VISION_DEGRADED_MODE, on_degraded)
    
    await bus.start()
    await worker.start()
    
    # Wait for the lazy health check in work() loop
    for _ in range(10):
        if len(degraded_events) > 0:
            break
        await asyncio.sleep(0.2)
        
    assert len(degraded_events) >= 1
    assert degraded_events[0]["reason"] == "tesseract_missing"
    assert degraded_events[0]["component"] == "ocr"
    
    await worker.stop()
    await bus.stop()


@pytest.mark.asyncio
async def test_oversized_image_rejection():
    validator = VisionValidator(max_bytes=100)
    # 100 bytes is very small for an image
    fake_data = b"fakedata" * 20 
    result = validator.validate_image(fake_data)
    assert result.allowed is False
    assert "oversized" in result.reason
