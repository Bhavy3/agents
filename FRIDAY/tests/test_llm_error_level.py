import logging
from unittest.mock import MagicMock
import pytest

from core.llm.local_llm_client import LocalLLMClient


@pytest.mark.asyncio
async def test_stream_exception_logged_at_error(caplog):
    client = LocalLLMClient()
    mock_http = MagicMock()
    mock_http.stream.side_effect = RuntimeError("simulated stream failure")
    client._get_client = lambda: mock_http

    with caplog.at_level(logging.DEBUG):
        async for _ in client.stream_generate("hello"):
            pass

    records = [
        r for r in caplog.records
        if (r.msg == "llm_generate_exception" or r.getMessage() == "llm_generate_exception")
    ]
    assert len(records) == 1
    assert records[0].levelname == "ERROR"


@pytest.mark.asyncio
async def test_health_check_exception_logged_at_error_and_no_stdout(caplog, capsys):
    client = LocalLLMClient()
    mock_http = MagicMock()
    mock_http.get.side_effect = RuntimeError("simulated health check failure")
    client._get_client = lambda: mock_http

    with caplog.at_level(logging.DEBUG):
        result = await client.health_check()

    assert result is False
    captured = capsys.readouterr()
    assert "[DIAGNOSTIC]" not in captured.out
    assert captured.out == ""

    records = [
        r for r in caplog.records
        if r.levelname == "ERROR" and (r.msg == "llm_health_check_failed" or r.getMessage() == "llm_health_check_failed")
    ]
    assert len(records) == 1
    assert getattr(records[0], "error", None) == repr(RuntimeError("simulated health check failure"))
