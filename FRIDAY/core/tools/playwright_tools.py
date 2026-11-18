"""Optional DOM-first browser automation adapter."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from .tool_models import ToolResult


class PlaywrightTools:
    def __init__(self) -> None:
        self._playwright: Any = None
        self._browser: Any = None
        self._page: Any = None

    async def _ensure_page(self) -> Any:
        if self._page is not None:
            return self._page
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise RuntimeError("Playwright is not installed; run pip install playwright and playwright install chromium") from exc
        self._playwright = await async_playwright().start()
        headed = os.getenv("FRIDAY_BROWSER_HEADED", "false").lower() == "true"
        self._browser = await self._playwright.chromium.launch(headless=not headed)
        context = await self._browser.new_context()
        self._page = await context.new_page()
        return self._page

    async def open(self, url: str) -> ToolResult:
        target = str(url)
        if target.startswith("workspace://"):
            root = Path(os.getenv("FRIDAY_WORKSPACE_ROOT") or os.getcwd()).expanduser().resolve()
            parsed = urlsplit(target)
            relative = Path(unquote(parsed.netloc)) / unquote(parsed.path.lstrip("/"))
            try:
                page_path = (root / relative).resolve(strict=True)
                if (
                    root not in page_path.parents
                    or not page_path.is_file()
                    or page_path.suffix.casefold() not in {".html", ".htm"}
                ):
                    raise ValueError("workspace preview must name an HTML file inside the workspace")
                target = page_path.as_uri()
            except (OSError, ValueError) as exc:
                return ToolResult(False, "", f"workspace preview rejected: {exc}")
        elif not target.startswith(("http://", "https://")):
            return ToolResult(False, "", "only http(s) URLs and confined workspace previews are allowed")
        try:
            page = await self._ensure_page()
            await page.goto(target, wait_until="domcontentloaded", timeout=30_000)
            return ToolResult(True, f"Opened {page.url}\nTitle: {await page.title()}")
        except Exception as exc:
            return ToolResult(False, "", str(exc))

    async def snapshot(self, max_chars: int = 12_000) -> ToolResult:
        try:
            page = await self._ensure_page()
            text = await page.locator("body").inner_text(timeout=10_000)
            return ToolResult(True, text[:max(500, min(int(max_chars), 30_000))])
        except Exception as exc:
            return ToolResult(False, "", str(exc))

    async def click(self, selector: str) -> ToolResult:
        try:
            page = await self._ensure_page()
            await page.locator(selector).first.click(timeout=15_000)
            return ToolResult(True, f"Clicked selector: {selector}")
        except Exception as exc:
            return ToolResult(False, "", str(exc))

    async def type_text(self, selector: str, text: str) -> ToolResult:
        try:
            page = await self._ensure_page()
            await page.locator(selector).first.fill(text, timeout=15_000)
            return ToolResult(True, f"Filled selector: {selector}")
        except Exception as exc:
            return ToolResult(False, "", str(exc))

    async def close(self) -> ToolResult:
        try:
            if self._browser is not None:
                await self._browser.close()
            if self._playwright is not None:
                await self._playwright.stop()
        finally:
            self._page = None
            self._browser = None
            self._playwright = None
        return ToolResult(True, "Browser closed.")
