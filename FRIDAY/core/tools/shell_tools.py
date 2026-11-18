"""Workspace-scoped command execution for coding workflows.

The tool deliberately requires the normal confirmation gate.  It gives FRIDAY
enough power to build and test a project without turning every model response
into unrestricted machine access.
"""

from __future__ import annotations

import asyncio
import os
import re
import shlex
import shutil
import subprocess
from pathlib import Path

from .tool_models import ToolResult

DEFAULT_SHELL_ALLOWLIST = frozenset({
    "python", "python3", "py", "pip", "pip3", "pytest",
    "git", "node", "nodejs", "npm", "npx",
    "cargo", "go", "echo", "dir", "ls", "cat", "exit",
})


class ShellTools:
    """Run bounded commands inside the configured FRIDAY workspace."""

    _blocked = re.compile(
        r"(?:\bformat\s+[a-z]:|\bshutdown\s+/|\breg\s+(?:delete|add)|"
        r"\brmdir\s+/s|\bdel\s+/s|remove-item\s+.*-recurse|"
        r"\b(?:rm|rmdir)\s+-rf\s+[/~]|powershell\s+.*-enc|"
        r"\bcertutil\b|\bcurl\b.*\|\s*(?:bash|sh|powershell)|"
        r"\biex\b|\binvoke-expression\b)",
        re.IGNORECASE,
    )

    def __init__(self, workspace_root: str | None = None) -> None:
        configured = workspace_root or os.getenv("FRIDAY_WORKSPACE_ROOT") or os.getcwd()
        self.workspace_root = Path(configured).expanduser().resolve()
        allow_env = os.getenv("FRIDAY_SHELL_ALLOW", "").strip()
        if allow_env == "*":
            self.allowlist: frozenset[str] | None = None
        elif allow_env:
            self.allowlist = frozenset(
                x.strip().casefold() for x in allow_env.split(",") if x.strip()
            )
        else:
            self.allowlist = DEFAULT_SHELL_ALLOWLIST

    def _cwd(self, directory: str = ".") -> Path:
        candidate = (self.workspace_root / directory).resolve()
        if candidate != self.workspace_root and self.workspace_root not in candidate.parents:
            raise ValueError("working directory must stay inside FRIDAY_WORKSPACE_ROOT")
        if not candidate.is_dir():
            raise ValueError(f"working directory does not exist: {directory}")
        return candidate

    async def execute_shell(
        self,
        command: str,
        directory: str = ".",
        timeout_seconds: float = 60.0,
    ) -> ToolResult:
        command = str(command or "").strip()
        if not command:
            return ToolResult(False, "", "command is required")
        if self._blocked.search(command):
            return ToolResult(False, "", "blocked command pattern", metadata={"exit_code": 1})

        try:
            parts = shlex.split(command, posix=True)
        except ValueError as exc:
            return ToolResult(False, "", f"malformed command: {exc}", metadata={"exit_code": 1})

        if not parts:
            return ToolResult(False, "", "command is empty")

        raw_bin = parts[0].casefold().replace("\\", "/").split("/")[-1]
        base_bin = re.sub(r"\.(exe|cmd|bat|ps1)$", "", raw_bin, flags=re.I)

        if self.allowlist is not None and base_bin not in self.allowlist:
            return ToolResult(
                False,
                "",
                f"command '{base_bin}' is not permitted by FRIDAY_SHELL_ALLOW allowlist",
                metadata={"exit_code": 1},
            )

        # On Windows, builtins like echo / dir / exit run via cmd.exe /d /c without shell=True
        if base_bin in {"echo", "dir", "exit"} and os.name == "nt":
            if any(op in parts for op in ("&", "&&", "|", "||", ";", ">", "<")):
                return ToolResult(
                    False,
                    "",
                    "shell chaining operators are not permitted",
                    metadata={"exit_code": 1},
                )
            exec_args = ["cmd.exe", "/d", "/c", *parts]
        else:
            exec_args = parts

        try:
            cwd = self._cwd(directory)
            timeout = max(1.0, min(float(timeout_seconds), 300.0))
            completed = await asyncio.to_thread(
                subprocess.run,
                exec_args,
                cwd=str(cwd),
                shell=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            output = (exc.stdout or "")[-20_000:]
            return ToolResult(
                False, output, f"command timed out after {timeout:g}s", metadata={"exit_code": None}
            )
        except Exception as exc:
            return ToolResult(False, "", str(exc), metadata={"exit_code": None})

        output = ((completed.stdout or "") + (completed.stderr or ""))[-20_000:]
        if completed.returncode != 0:
            return ToolResult(
                False, output, f"exit code {completed.returncode}",
                metadata={"exit_code": completed.returncode},
            )
        return ToolResult(
            True, output or "Command completed successfully.", metadata={"exit_code": 0}
        )
