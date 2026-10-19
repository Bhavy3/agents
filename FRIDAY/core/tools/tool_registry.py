from typing import Callable, Dict, Any
from .browser_tools import BrowserTools
from .filesystem_tools import FilesystemTools
from .desktop_tools import DesktopTools
from .system_tools import SystemTools


class ToolRegistry:
    """Central registry for all executable tools in FRIDAY."""

    def __init__(self, event_bus: Any = None):
        self._tools: Dict[str, Callable[..., Any]] = {}
        self._event_bus = event_bus
        
        # Instantiate tool collections
        self._browser = BrowserTools()
        self._fs = FilesystemTools()
        self._desktop = DesktopTools()
        self._system = SystemTools()
        
        self._register_defaults()

    def _register_defaults(self):
        # Browser
        self.register("open_url", self._browser.open_url)
        self.register("search_web", self._browser.search_web)
        
        # Filesystem
        self.register("list_dir", self._fs.list_dir)
        self.register("read_text_file", self._fs.read_text_file)
        self.register("write_text_file", self._fs.write_text_file)
        self.register("search_files", self._fs.search_files)
        
        # Desktop
        self.register("launch_app", self._desktop.launch_app)
        self.register("press_key", self._desktop.press_key)
        self.register("keyboard_shortcut", self._desktop.keyboard_shortcut)
        self.register("move_mouse_to", self._desktop.move_mouse_to)

        # Memory
        self.register("remember", self._remember)
        self.register("get_time", self._system.get_time)

    async def _remember(self, fact: str = "", text: str = "", content: str = "", **kwargs) -> Any:
        from .tool_models import ToolResult
        from ..events.event_types import EventType
        from ..events.models import Event
        remembered_text = str(fact or text or content or kwargs.get("value", "")).strip()
        if not remembered_text:
            return ToolResult(False, "", "No content provided to remember")

        # Persistent-injection guard: Cap at 300 characters on a sentence or word boundary
        if len(remembered_text) > 300:
            truncated = remembered_text[:300]
            # Try sentence boundary
            for punct in (". ", "! ", "? "):
                idx = truncated.rfind(punct)
                if idx > 150:
                    truncated = truncated[:idx + 1]
                    break
            else:
                # Word boundary
                idx = truncated.rfind(" ")
                if idx > 150:
                    truncated = truncated[:idx]
            remembered_text = truncated.strip()

        source = kwargs.get("source", "workflow_remember_tool")
        derived_from = kwargs.get("derived_from", "web_search")

        if self._event_bus:
            await self._event_bus.publish(Event.create(
                EventType.MEMORY_WRITE_REQUEST,
                {
                    "type": "approved_fact",
                    "content": remembered_text,
                    "source": source,
                    "derived_from": derived_from,
                    "explicit_user_approved": True,
                },
                "tool_registry",
            ))
        return ToolResult(True, f"Remembered: {remembered_text}")

    def register(self, name: str, func: Callable[..., Any]):
        self._tools[name] = func

    def get_tool(self, name: str) -> Callable[..., Any] | None:
        return self._tools.get(name)

    def list_tools(self) -> list[str]:
        return list(self._tools.keys())
