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
