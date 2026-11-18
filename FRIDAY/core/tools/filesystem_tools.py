import os
import re
import asyncio
from pathlib import Path
from typing import Any

from .tool_models import ToolResult


# Windows resolves these names to character devices regardless of extension.
_RESERVED_WINDOWS_NAMES = re.compile(
    r"^(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])$",
    re.IGNORECASE,
)


class FilesystemTools:
    """Filesystem operations confined to FRIDAY_WORKSPACE_ROOT.

    Every path is resolved through :meth:`_resolve_safe`, which rejects device
    namespaces, Windows reserved device names, and any path whose canonical
    form escapes the configured workspace root.  Confinement happens after
    ``resolve()`` so ``..`` traversal and symlink escapes are both caught.
    """

    def __init__(self, workspace_root: str | None = None) -> None:
        configured = workspace_root or os.getenv("FRIDAY_WORKSPACE_ROOT") or os.getcwd()
        self.workspace_root = Path(configured).expanduser().resolve()

    def _resolve_safe(self, file_path: str) -> Path:
        """Resolve a path and reject anything outside the workspace root."""
        raw = str(file_path or "").strip()
        if not raw:
            raise ValueError("path is required")

        # Device namespaces (\\?\, \\.\) and UNC shares bypass normal path rules.
        if raw.startswith("\\\\") or raw.startswith("//"):
            raise ValueError(f"UNC and device paths are not allowed: {raw}")

        leaf = Path(raw).name
        if _RESERVED_WINDOWS_NAMES.match(leaf.split(".")[0]):
            raise ValueError(f"reserved Windows device name is not allowed: {raw}")

        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            candidate = self.workspace_root / candidate
        candidate = candidate.resolve()

        if candidate != self.workspace_root and self.workspace_root not in candidate.parents:
            raise ValueError(
                f"Access denied: path '{raw}' escapes FRIDAY_WORKSPACE_ROOT"
            )
        return candidate

    async def list_dir(self, directory: str = ".") -> ToolResult:
        try:
            path = self._resolve_safe(directory)
            if not path.is_dir():
                return ToolResult(False, "", f"Path is not a directory: {directory}")

            items = await asyncio.to_thread(os.listdir, path)
            return ToolResult(True, "\n".join(items))
        except Exception as e:
            return ToolResult(False, "", str(e))

    async def read_text_file(self, file_path: str) -> ToolResult:
        try:
            path = self._resolve_safe(file_path)
            if not path.is_file():
                return ToolResult(False, "", f"File not found: {file_path}")

            # Bound read size
            stat = await asyncio.to_thread(path.stat)
            if stat.st_size > 1024 * 1024: # 1MB limit
                 return ToolResult(False, "", "File too large to read (max 1MB)")

            content = await asyncio.to_thread(path.read_text, encoding="utf-8", errors="replace")
            return ToolResult(True, content)
        except Exception as e:
            return ToolResult(False, "", str(e))

    async def write_text_file(self, file_path: str, content: str) -> ToolResult:
        try:
            path = self._resolve_safe(file_path)
            # Ensure parent exists
            await asyncio.to_thread(path.parent.mkdir, parents=True, exist_ok=True)
            await asyncio.to_thread(path.write_text, content, encoding="utf-8")
            return ToolResult(True, f"Successfully wrote {len(content)} characters to {file_path}")
        except Exception as e:
            return ToolResult(False, "", str(e))

    async def search_files(self, pattern: str, directory: str = ".") -> ToolResult:
        try:
            path = self._resolve_safe(directory)
            matches = []
            # Non-recursive glob for safety
            for p in path.glob(pattern):
                matches.append(str(p.name))
            return ToolResult(True, "\n".join(matches) if matches else "No matches found")
        except Exception as e:
            return ToolResult(False, "", str(e))
