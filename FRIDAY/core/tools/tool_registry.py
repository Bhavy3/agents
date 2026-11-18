from typing import Callable, Dict, Any
from .browser_tools import BrowserTools
from .filesystem_tools import FilesystemTools
from .desktop_tools import DesktopTools
from .system_tools import SystemTools
from .shell_tools import ShellTools
from .agent_desktop_tools import AgentDesktopTools
from .playwright_tools import PlaywrightTools
from .n8n_tools import N8nTools


class ToolRegistry:
    """Central registry for all executable tools in FRIDAY."""

    def __init__(self, event_bus: Any = None, query_client: Any = None):
        self._tools: Dict[str, Callable[..., Any]] = {}
        self._event_bus = event_bus
        
        # Instantiate tool collections
        self._browser = BrowserTools(query_client=query_client)
        self._fs = FilesystemTools()
        self._desktop = DesktopTools()
        self._system = SystemTools()
        self._shell = ShellTools()
        self._agent_desktop = AgentDesktopTools()
        self._playwright = PlaywrightTools()
        self._n8n = N8nTools()
        
        self._register_defaults()

    def _register_defaults(self):
        # Browser
        self.register("open_url", self._browser.open_url)
        self.register("search_web", self._browser.search_web)
        self.register("research_web", self._browser.research_web)
        self.register("open_section", self._browser.open_section)
        
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
        self.register("memory_recall", self._recall)
        self.register("get_time", self._system.get_time)

        # Coding and browser automation. Optional integrations return a clear
        # ToolResult when their runtime is not installed or configured.
        self.register("execute_shell", self._shell.execute_shell)
        self.register("desktop_list_apps", self._agent_desktop.list_apps)
        self.register("desktop_snapshot", self._agent_desktop.snapshot)
        self.register("desktop_find", self._agent_desktop.find)
        self.register("desktop_click", self._agent_desktop.click)
        self.register("desktop_type", self._agent_desktop.type_text)
        self.register("desktop_launch", self._agent_desktop.launch)
        self.register("browser_open", self._playwright.open)
        self.register("browser_snapshot", self._playwright.snapshot)
        self.register("browser_click", self._playwright.click)
        self.register("browser_type", self._playwright.type_text)
        self.register("browser_close", self._playwright.close)

        # n8n workflow automation
        self.register("n8n_create_workflow", self._n8n.create_workflow)
        self.register("n8n_list_workflows", self._n8n.list_workflows)

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

    async def _recall(self, query: str = "", **kwargs) -> Any:
        from .tool_models import ToolResult
        from ..memory.memory_store import MemoryStore
        recall_query = str(query or kwargs.get("text") or kwargs.get("fact") or kwargs.get("input") or "").strip()
        if not recall_query:
            return ToolResult(False, "", "No query provided for memory recall")
        store = getattr(self, "_memory_store", None)
        if store is None:
            store = MemoryStore()
            self._memory_store = store
        records = await store.search_by_text(recall_query, limit=int(kwargs.get("limit", 5)))
        if not records:
            return ToolResult(True, "No matching memories found.", metadata={"count": 0})
        formatted = "\n".join(f"[{r.type.value}] {r.content}" for r in records)
        return ToolResult(
            True,
            formatted,
            metadata={"count": len(records), "records": [{"id": r.id, "type": r.type.value, "content": r.content} for r in records]},
        )

    def register(self, name: str, func: Callable[..., Any]):
        self._tools[name] = func

    def get_tool(self, name: str) -> Callable[..., Any] | None:
        return self._tools.get(name)

    def list_tools(self) -> list[str]:
        return list(self._tools.keys())
