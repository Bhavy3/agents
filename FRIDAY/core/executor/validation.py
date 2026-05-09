from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ActionRisk(StrEnum):
    SAFE = "safe"
    RESTRICTED = "restricted"
    DANGEROUS = "dangerous"
    FORBIDDEN = "forbidden"


@dataclass(slots=True, frozen=True)
class ValidationResult:
    allowed: bool
    requires_confirmation: bool
    risk_level: ActionRisk
    reason: str


_FORBIDDEN_PATTERNS = {
    "rm -rf",
    "format c:",
    "del /s /q",
    "powershell -encodedcommand",
}

_DANGEROUS_TERMS = {
    "delete", "remove", "kill", "force", "registry", "shutdown", "restart"
}

_RESTRICTED_TERMS = {
    "install", "email", "send", "message", "upload", "download"
}


class CommandValidationPipeline:
    def validate(self, intent: str, parameters: dict[str, str]) -> ValidationResult:
        if not intent.strip():
            return ValidationResult(False, False, ActionRisk.FORBIDDEN, "Empty intent is invalid.")
        
        joined = " ".join([intent, *parameters.values()]).lower()
        
        # 1. Forbidden check
        if any(pattern in joined for pattern in _FORBIDDEN_PATTERNS):
            return ValidationResult(False, False, ActionRisk.FORBIDDEN, "Forbidden execution pattern detected.")
        
        # 2. Parameter safety
        if any(len(value) > 2000 for value in parameters.values()):
            return ValidationResult(False, False, ActionRisk.FORBIDDEN, "Parameter length exceeds safety limit.")

        # 3. Risk classification
        if any(term in joined for term in _DANGEROUS_TERMS):
            return ValidationResult(False, True, ActionRisk.DANGEROUS, "High-risk action requires manual confirmation.")
        
        if any(term in joined for term in _RESTRICTED_TERMS):
            return ValidationResult(True, True, ActionRisk.RESTRICTED, "Restricted action requires confirmation.")

        return ValidationResult(True, False, ActionRisk.SAFE, "Action passed safety validation.")
