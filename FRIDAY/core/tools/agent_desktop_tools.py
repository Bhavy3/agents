"""Optional Agent Desktop adapter.

Agent Desktop is intentionally invoked through its JSON CLI contract.  The
adapter remains usable when the binary is not installed and never logs the
contents typed into an application.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
from typing import Any

from .tool_models import ToolResult


class AgentDesktopTools:
    def __init__(self, executable: str | None = None) -> None:
        self.executable = executable or os.getenv("FRIDAY_AGENT_DESKTOP_BIN", "agent-desktop")
        self.allowed_apps = {
            name.strip().casefold()
            for name in os.getenv("FRIDAY_DESKTOP_APPS", "").split(",")
            if name.strip()
        }

    def _check_binary(self) -> str | None:
        return shutil.which(self.executable)

    def _check_app(self, app: str) -> str | None:
        if not app.strip():
            return "app is required"
        if self.allowed_apps and app.casefold() not in self.allowed_apps:
            return f"app is not in FRIDAY_DESKTOP_APPS: {app}"
        if not self.allowed_apps:
            return "FRIDAY_DESKTOP_APPS is not configured"
        return None

    async def _run(self, *args: str, timeout_seconds: float = 45.0) -> ToolResult:
        binary = self._check_binary()
        if binary is None:
            return ToolResult(False, "", f"Agent Desktop executable not found: {self.executable}")
        try:
            completed = await asyncio.to_thread(
                subprocess.run,
                [binary, *args],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=max(1.0, min(float(timeout_seconds), 60.0)),
            )
        except Exception as exc:
            return ToolResult(False, "", str(exc))

        raw = (completed.stdout or completed.stderr or "").strip()
        if completed.returncode != 0:
            return ToolResult(False, raw, f"agent-desktop exit code {completed.returncode}")
        try:
            payload: Any = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            return ToolResult(False, raw, "agent-desktop returned invalid JSON")
        if isinstance(payload, dict) and payload.get("ok") is False:
            error = payload.get("error")
            return ToolResult(False, raw, str(error or "agent-desktop command failed"))
        return ToolResult(True, raw or json.dumps(payload))

    async def list_apps(self) -> ToolResult:
        return await self._run("list-apps")

    async def snapshot(self, app: str, window_id: str = "") -> ToolResult:
        error = self._check_app(app)
        if error:
            return ToolResult(False, "", error)
        args = ["snapshot", "--app", app, "-i"]
        if window_id:
            args.extend(["--window-id", window_id])
        return await self._run(*args)

    async def find(self, app: str, text: str) -> ToolResult:
        error = self._check_app(app)
        if error:
            return ToolResult(False, "", error)
        if not text.strip():
            return ToolResult(False, "", "text is required")
        return await self._run("find", "--app", app, text)

    async def click(self, ref: str) -> ToolResult:
        if not self.allowed_apps:
            return ToolResult(False, "", "FRIDAY_DESKTOP_APPS is not configured")
        if not ref.strip():
            return ToolResult(False, "", "ref is required")
        return await self._run("click", ref)

    async def type_text(self, ref: str, text: str) -> ToolResult:
        if not self.allowed_apps:
            return ToolResult(False, "", "FRIDAY_DESKTOP_APPS is not configured")
        if not ref.strip() or not text:
            return ToolResult(False, "", "ref and text are required")
        return await self._run("type", ref, text)

    async def launch(self, app: str) -> ToolResult:
        error = self._check_app(app)
        if error:
            return ToolResult(False, "", error)
        return await self._run("launch", app)
