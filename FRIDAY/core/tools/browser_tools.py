import asyncio
import html
import logging
from urllib.parse import urlsplit
import webbrowser
from ddgs import DDGS
from .tool_models import ToolResult

logger = logging.getLogger(__name__)

MAX_SEARCH_RESULTS = 5
MAX_SEARCH_RESULT_CHARS = 1500
SEARCH_TIMEOUT_SECONDS = 8


class BrowserTools:
    """Browser interactions and bounded keyless web search."""

    async def open_url(self, url: str) -> ToolResult:
        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        try:
            parsed = urlsplit(url)
            host = parsed.hostname or ""
        except Exception:
            return ToolResult(False, "", "invalid_url")

        tld = host.rsplit(".", 1)[-1] if "." in host else ""
        if "." not in host or not (tld.isalpha() and len(tld) >= 2):
            return ToolResult(False, "", "invalid_url")

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
        """Return up to five short text results without opening a browser."""
        normalized_query = " ".join(query.split())[:500]
        if not normalized_query:
            logger.error("web_search_empty_query")
            return ToolResult(False, "I couldn't reach the web right now.", "empty_query")

        try:
            results = await asyncio.wait_for(
                asyncio.to_thread(
                    lambda: DDGS(timeout=SEARCH_TIMEOUT_SECONDS).text(
                        normalized_query,
                        max_results=MAX_SEARCH_RESULTS,
                    )
                ),
                timeout=SEARCH_TIMEOUT_SECONDS + 1,
            )
        except Exception as exc:
            logger.exception("web_search_failed", extra={"query_length": len(normalized_query)})
            return ToolResult(False, "I couldn't reach the web right now.", str(exc))

        entries: list[str] = []
        used_chars = 0
        for result in results[:MAX_SEARCH_RESULTS]:
            title = html.escape(" ".join(str(result.get("title", "")).split()), quote=False)
            snippet = html.escape(" ".join(str(result.get("body", "")).split()), quote=False)
            if not title and not snippet:
                continue
            entry = f"{len(entries) + 1}. {title}\n{snippet}".strip()
            remaining = MAX_SEARCH_RESULT_CHARS - used_chars
            if remaining <= 0:
                break
            if entries:
                remaining -= 1
            if len(entry) > remaining:
                entry = entry[:remaining].rstrip()
            if not entry:
                break
            entries.append(entry)
            used_chars += len(entry) + (1 if len(entries) > 1 else 0)

        if not entries:
            logger.error("web_search_empty_results", extra={"query_length": len(normalized_query)})
            return ToolResult(False, "I couldn't reach the web right now.", "empty_results")

        return ToolResult(True, "\n".join(entries)[:MAX_SEARCH_RESULT_CHARS])
