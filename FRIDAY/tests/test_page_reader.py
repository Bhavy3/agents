from __future__ import annotations

from unittest.mock import AsyncMock
import httpx
import pytest

from core.tools.page_reader import extract_relevant_text, fetch_page

SAMPLE_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Solar Info</title>
    <script>
        var config = {"topic": "solar panels", "active": true};
    </script>
    <style>
        body { font-family: sans-serif; }
    </style>
</head>
<body>
    <p>Solar panels convert sunlight into electricity.</p>
    <p>Wind turbines generate power from wind.</p>
</body>
</html>
"""


def test_a_extract_relevant_text_ignores_scripts():
    res = extract_relevant_text(SAMPLE_HTML, "solar panels", max_chars=400)
    assert "Solar panels convert sunlight into electricity." in res
    assert "var config" not in res
    assert "topic" not in res


def test_b_extract_relevant_text_no_match():
    assert extract_relevant_text(SAMPLE_HTML, "xyzzy", max_chars=400) == ""


def test_c_extract_relevant_text_max_chars():
    res = extract_relevant_text(SAMPLE_HTML, "solar", max_chars=20)
    assert len(res) <= 20
    assert len(res) > 0


@pytest.mark.asyncio
async def test_d_fetch_page_timeout_returns_none(monkeypatch):
    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None
    mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("timed out"))

    monkeypatch.setattr(httpx, "AsyncClient", lambda *args, **kwargs: mock_client)

    result = await fetch_page("https://example.com")
    assert result is None
