from dataclasses import dataclass
from typing import Any


@dataclass(slots=True, frozen=True)
class ScreenshotData:
    image_bytes: bytes
    format: str
    width: int
    height: int
    timestamp: float


@dataclass(slots=True, frozen=True)
class OCRResult:
    text: str
    latency_ms: float
    confidence: float = 1.0


@dataclass(slots=True, frozen=True)
class WindowContext:
    title: str
    app_name: str
    is_focused: bool
