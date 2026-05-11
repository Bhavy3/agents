import asyncio
from typing import Any
from ..events.bus import EventBus
from ..events.event_types import EventType
from ..events.models import Event


class VisualContextManager:
    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus
        self._current_window = None
        self._last_ocr_text = ""
        self._is_capturing = False

    def start(self):
        self.event_bus.subscribe(EventType.ACTIVE_WINDOW_CONTEXT_READY, self._on_window_context)
        self.event_bus.subscribe(EventType.SCREEN_CAPTURE_COMPLETED, self._on_capture_completed)
        self.event_bus.subscribe(EventType.OCR_COMPLETED, self._on_ocr_completed)
        self.event_bus.subscribe(EventType.VISUAL_CONTEXT_REQUESTED, self._request_full_update)

    async def _on_window_context(self, event: Event):
        self._current_window = event.payload

    async def _on_capture_completed(self, event: Event):
        # Chain capture to OCR automatically
        await self.event_bus.publish(Event.create(
            EventType.OCR_REQUESTED,
            {"image_bytes": event.payload["image_bytes"]},
            "visual_context_manager",
            event.correlation_id
        ))

    async def _on_ocr_completed(self, event: Event):
        self._last_ocr_text = event.payload.get("text", "")
        self._is_capturing = False
        
        # Emit final summary
        summary = self.get_summary()
        await self.event_bus.publish(Event.create(
            EventType.VISUAL_CONTEXT_READY,
            {"summary": summary},
            "visual_context_manager",
            event.correlation_id
        ))

    async def _request_full_update(self, event: Event):
        if self._is_capturing:
            return
            
        self._is_capturing = True
        await self.event_bus.publish(Event.create(
            EventType.SCREEN_CAPTURE_REQUESTED,
            {},
            "visual_context_manager",
            event.correlation_id
        ))

    def get_summary(self) -> str:
        parts = []
        if self._current_window:
            parts.append(f"Active Window: {self._current_window.get('title')}")
            parts.append(f"Focused App: {self._current_window.get('app_name')}")
        
        if self._last_ocr_text:
            # Bounded summary to avoid prompt blowup
            preview = self._last_ocr_text[:800]
            parts.append(f"Screen Content Snippet: {preview}")
            
        return "\n".join(parts) if parts else "No visual context detected."
