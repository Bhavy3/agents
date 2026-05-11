import re
from typing import Any, NamedTuple
from .tool_models import ToolRisk


class ToolValidationResult(NamedTuple):
    allowed: bool
    risk: ToolRisk = ToolRisk.SAFE
    reason: str | None = None


class ToolValidator:
    def __init__(self):
        # High-risk patterns that are always FORBIDDEN
        self._forbidden_patterns = [
            re.compile(r"rm\s+-rf\s+[/~]"),
            re.compile(r"format\s+[a-z]:", re.IGNORECASE),
            re.compile(r"powershell\s+.*-enc", re.IGNORECASE),
            re.compile(r"shutdown\s+/[st]", re.IGNORECASE),
            re.compile(r"mkfs", re.IGNORECASE),
            re.compile(r"mv\s+.*\s+/dev/null"),
            re.compile(r"dd\s+if="),
        ]

        # Protected paths for filesystem tools
        self._protected_paths = [
            r"C:\Windows",
            r"C:\System32",
            r"~/.ssh",
            r"AppData\Local\Google\Chrome\User Data", # Credential stores
        ]

    def validate_request(self, tool_name: str, params: dict[str, Any]) -> ToolValidationResult:
        if not tool_name:
            return ToolValidationResult(False, ToolRisk.FORBIDDEN, "missing_tool_name")

        # Convert params to string for global pattern checking
        param_str = str(params)
        for pattern in self._forbidden_patterns:
            if pattern.search(param_str):
                return ToolValidationResult(False, ToolRisk.FORBIDDEN, f"forbidden_pattern: {pattern.pattern}")

        # Path protection
        for path in params.values():
            if isinstance(path, str):
                for protected in self._protected_paths:
                    if protected.lower() in path.lower():
                        return ToolValidationResult(False, ToolRisk.FORBIDDEN, f"protected_path_access: {protected}")

        # Risk level deduction
        risk = ToolRisk.SAFE
        
        # Tools that are inherently RESTRICTED or DANGEROUS
        if tool_name in ["delete_file", "terminate_process"]:
            risk = ToolRisk.RESTRICTED
        elif tool_name in ["execute_shell", "edit_system_config"]:
            risk = ToolRisk.DANGEROUS
            
        # Parameter-based risk escalation
        param_str_lower = param_str.lower()
        if "force" in param_str_lower or "recursive" in param_str_lower:
            if risk == ToolRisk.RESTRICTED:
                risk = ToolRisk.DANGEROUS

        return ToolValidationResult(True, risk)
