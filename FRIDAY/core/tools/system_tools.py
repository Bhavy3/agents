from datetime import datetime

from .tool_models import ToolResult


class SystemTools:
    """Read-only tools for facts available from the local runtime."""

    async def get_time(self) -> ToolResult:
        now = datetime.now().astimezone()
        local_time = now.strftime("%I:%M %p")
        timezone_name = now.tzname() or "local time"
        return ToolResult(True, f"The local time is {local_time} {timezone_name}.")
