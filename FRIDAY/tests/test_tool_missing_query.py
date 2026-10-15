from unittest.mock import AsyncMock, MagicMock
import pytest

from core.events.event_types import EventType
from core.tools.tool_models import ToolRisk
from core.tools.tool_worker import ToolWorker


@pytest.mark.asyncio
async def test_search_web_missing_query_does_not_call_tool():
    bus = MagicMock()
    bus.publish = AsyncMock()

    worker = ToolWorker(bus)
    fake_tool = AsyncMock()
    worker.registry.register("search_web", fake_tool)

    result = await worker.execute_tool("search_web", {}, "corr-123", ToolRisk.SAFE)

    assert not fake_tool.called
    assert not result.success
    assert result.error == "missing_query"

    failed_events = [
        call.args[0] for call in bus.publish.call_args_list
        if call.args and call.args[0].event_type == EventType.ACTION_FAILED
    ]
    assert len(failed_events) >= 1
    assert failed_events[0].payload.get("tool_name") == "search_web"
    assert failed_events[0].payload.get("error") == "missing_query"
