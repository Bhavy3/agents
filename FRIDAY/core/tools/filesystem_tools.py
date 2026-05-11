import os
import asyncio
from pathlib import Path
from typing import Any
from .tool_models import ToolResult


class FilesystemTools:
    """Safe filesystem operations with path resolution and basic protections."""

    async def list_dir(self, directory: str = ".") -> ToolResult:
        try:
            path = Path(directory).expanduser().resolve()
            if not path.is_dir():
                return ToolResult(False, "", f"Path is not a directory: {directory}")
            
            items = await asyncio.to_thread(os.listdir, path)
            return ToolResult(True, "\n".join(items))
        except Exception as e:
            return ToolResult(False, "", str(e))

    async def read_text_file(self, file_path: str) -> ToolResult:
        try:
            path = Path(file_path).expanduser().resolve()
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
            path = Path(file_path).expanduser().resolve()
            # Ensure parent exists
            await asyncio.to_thread(path.parent.mkdir, parents=True, exist_ok=True)
            await asyncio.to_thread(path.write_text, content, encoding="utf-8")
            return ToolResult(True, f"Successfully wrote {len(content)} characters to {file_path}")
        except Exception as e:
            return ToolResult(False, "", str(e))

    async def search_files(self, pattern: str, directory: str = ".") -> ToolResult:
        try:
            path = Path(directory).expanduser().resolve()
            matches = []
            # Non-recursive glob for safety
            for p in path.glob(pattern):
                matches.append(str(p.name))
            return ToolResult(True, "\n".join(matches) if matches else "No matches found")
        except Exception as e:
            return ToolResult(False, "", str(e))
