from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from core.tools.playwright_tools import PlaywrightTools


@pytest.mark.asyncio
async def test_workspace_preview_opens_only_a_file_inside_workspace(tmp_path, monkeypatch):
    project = tmp_path / "food-demo"
    project.mkdir()
    page_file = project / "index.html"
    page_file.write_text("<h1>Food</h1>", encoding="utf-8")
    monkeypatch.setenv("FRIDAY_WORKSPACE_ROOT", str(tmp_path))

    class Page:
        url = ""

        async def goto(self, url, **kwargs):
            self.url = url

        async def title(self):
            return "Food"

    page = Page()
    tools = PlaywrightTools()
    async def ensure_page():
        return page
    tools._ensure_page = ensure_page

    result = await tools.open("workspace://food-demo/index.html")

    assert result.success
    assert page.url == page_file.as_uri()


@pytest.mark.asyncio
async def test_workspace_preview_rejects_path_escape(tmp_path, monkeypatch):
    monkeypatch.setenv("FRIDAY_WORKSPACE_ROOT", str(tmp_path))
    tools = PlaywrightTools()

    result = await tools.open("workspace://..%2Foutside/index.html")

    assert not result.success
    assert "workspace preview rejected" in result.error
