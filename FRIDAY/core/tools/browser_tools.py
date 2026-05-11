import webbrowser
import asyncio
from .tool_models import ToolResult


class BrowserTools:
    """Lightweight browser interactions using standard library."""

    async def open_url(self, url: str) -> ToolResult:
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
            
        try:
            # webbrowser.open is blocking in some OS, but usually fine. 
            # We use to_thread to be safe.
            success = await asyncio.to_thread(webbrowser.open, url)
            if success:
                return ToolResult(True, f"Successfully requested browser to open: {url}")
            else:
                return ToolResult(False, "", "Browser failed to launch or open URL")
        except Exception as e:
            return ToolResult(False, "", f"Browser error: {str(e)}")

    async def search_web(self, query: str) -> ToolResult:
        """Search Google for the given query."""
        search_url = f"https://www.google.com/search?q={query.replace(' ', '+')}"
        return await self.open_url(search_url)
