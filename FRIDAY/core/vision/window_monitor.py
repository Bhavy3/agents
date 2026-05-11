import asyncio
from typing import Any
import pygetwindow as gw
from ..workers.base_worker import BaseWorker
from ..events.bus import EventBus
from ..events.event_types import EventType
from ..events.models import Event


class WindowMonitorWorker(BaseWorker):
    def __init__(self, event_bus: EventBus):
        super().__init__("window_monitor", event_bus)
        self._last_active_window = None

    async def work(self) -> None:
        while not self.should_stop:
            try:
                # Poll active window in thread pool
                active_window_title = await asyncio.to_thread(self._get_active_window_sync)
                
                if active_window_title and active_window_title != self._last_active_window:
                    self._last_active_window = active_window_title
                    
                    # Emit focus change
                    await self.event_bus.publish(Event.create(
                        EventType.WINDOW_FOCUS_CHANGED,
                        {"title": active_window_title},
                        self.name
                    ))
                    
                    # Deduce app name (usually the last part of title on Windows)
                    app_name = active_window_title.split(" - ")[-1] if " - " in active_window_title else active_window_title
                    
                    await self.event_bus.publish(Event.create(
                        EventType.ACTIVE_WINDOW_CONTEXT_READY,
                        {"title": active_window_title, "app_name": app_name},
                        self.name
                    ))
            except Exception:
                # Window enumeration can be flaky on some systems, suppress noise
                pass
                
            self.heartbeat(f"monitoring [active={self._last_active_window}]")
            await asyncio.sleep(2.0)

    def _get_active_window_sync(self) -> str | None:
        try:
            window = gw.getActiveWindow()
            return window.title if window else None
        except Exception:
            return None
