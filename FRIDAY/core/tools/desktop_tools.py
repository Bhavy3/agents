import asyncio
import subprocess
import pyautogui
from .tool_models import ToolResult


class DesktopTools:
    """Desktop automation and application management."""

    async def launch_app(self, command: str) -> ToolResult:
        """Launch an application via shell command."""
        try:
            # We use subprocess.Popen so it doesn't block the worker
            # shell=True is needed for 'start' or complex commands on Windows
            process = await asyncio.to_thread(subprocess.Popen, command, shell=True)
            return ToolResult(True, f"Application launch sequence initiated: {command} (PID: {process.pid})")
        except Exception as e:
            return ToolResult(False, "", f"Launch failed: {str(e)}")

    async def press_key(self, key: str) -> ToolResult:
        """Press a keyboard key (e.g., 'enter', 'tab', 'esc')."""
        try:
            await asyncio.to_thread(pyautogui.press, key)
            return ToolResult(True, f"Pressed key: {key}")
        except Exception as e:
            return ToolResult(False, "", f"Key press failed: {str(e)}")

    async def keyboard_shortcut(self, keys: list[str]) -> ToolResult:
        """Execute a keyboard shortcut (e.g., ['ctrl', 'c'])."""
        try:
            await asyncio.to_thread(pyautogui.hotkey, *keys)
            return ToolResult(True, f"Executed shortcut: {'+'.join(keys)}")
        except Exception as e:
            return ToolResult(False, "", f"Shortcut failed: {str(e)}")

    async def move_mouse_to(self, x: int, y: int) -> ToolResult:
        """Move mouse to specific coordinates."""
        try:
            # Disable failsafe for small movements? No, keep it enabled for safety.
            await asyncio.to_thread(pyautogui.moveTo, x, y, duration=0.2)
            return ToolResult(True, f"Moved mouse to {x}, {y}")
        except Exception as e:
            return ToolResult(False, "", f"Mouse move failed: {str(e)}")
