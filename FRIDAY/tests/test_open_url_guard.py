from unittest.mock import patch
import pytest

from core.tools.browser_tools import BrowserTools


@pytest.mark.asyncio
async def test_open_url_invalid_domain_without_dot():
    # Case a: open_url("https://theat") must NOT call webbrowser.open and must return success=False.
    tools = BrowserTools()
    with patch("webbrowser.open") as mock_open:
        res = await tools.open_url("https://theat")
        assert not mock_open.called
        assert res.success is False


@pytest.mark.asyncio
async def test_open_url_valid_domain():
    # Case b: open_url("https://www.weather.com") must call webbrowser.open once with that URL.
    tools = BrowserTools()
    with patch("webbrowser.open", return_value=True) as mock_open:
        res = await tools.open_url("https://www.weather.com")
        mock_open.assert_called_once_with("https://www.weather.com")
        assert res.success is True


@pytest.mark.asyncio
async def test_open_url_empty_host():
    # Case c: open_url("https://") must NOT call webbrowser.open.
    tools = BrowserTools()
    with patch("webbrowser.open") as mock_open:
        res = await tools.open_url("https://")
        assert not mock_open.called
        assert res.success is False


@pytest.mark.asyncio
async def test_open_url_raw_word_without_scheme_or_dot():
    # Case d: open_url("theat") must NOT call webbrowser.open.
    tools = BrowserTools()
    with patch("webbrowser.open") as mock_open:
        res = await tools.open_url("theat")
        assert not mock_open.called
        assert res.success is False
