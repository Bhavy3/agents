import re

import pytest

from core.tools.tool_registry import ToolRegistry


@pytest.mark.asyncio
async def test_registered_get_time_tool_returns_local_time_and_zone():
    tool = ToolRegistry().get_tool("get_time")
    assert tool is not None

    result = await tool()

    assert result.success
    assert re.fullmatch(r"The local time is \d{2}:\d{2} [AP]M .+\.", result.output)
