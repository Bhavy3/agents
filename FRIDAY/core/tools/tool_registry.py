from typing import Callable, Dict, Any
from .browser_tools import BrowserTools
from .filesystem_tools import FilesystemTools
from .desktop_tools import DesktopTools


class ToolRegistry:
    """Central registry for all executable tools in FRIDAY."""

    def __init__(self):
        self._tools: Dict[str, Callable[..., Any]] = {}
        
        # Instantiate tool collections
        self._browser = BrowserTools()
        self._fs = FilesystemTools()
        self._desktop = DesktopTools()
        
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

    def register(self, name: str, func: Callable[..., Any]):
        self._tools[name] = func

    def get_tool(self, name: str) -> Callable[..., Any] | None:
        return self._tools.get(name)

    def list_tools(self) -> list[str]:
        return list(self._tools.keys())
