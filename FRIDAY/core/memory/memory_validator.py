import json
import math
import re
from typing import NamedTuple
from core.memory.memory_models import MemoryRecord, MemoryType


class ValidationResult(NamedTuple):
    allowed: bool
    reason: str | None = None


class MemoryValidator:
    def __init__(
        self,
        max_content_length: int = 2000,
        max_metadata_keys: int = 20
    ):
        self.max_content_length = max_content_length
        self.max_metadata_keys = max_metadata_keys

        # Patterns for secrets (API keys, JWT, SSH)
        self._forbidden_patterns = [
            re.compile(r"AIza[0-9A-Za-z\\-_]{35}"),  # Google API Keys
            re.compile(r"sk-[a-zA-Z0-9]{48}"),       # OpenAI
            re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),  # AWS access key IDs
            re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b"),
            re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
            re.compile(r"-----BEGIN [A-Z ]+ PRIVATE KEY-----"),
            re.compile(r"eyJ[a-zA-Z0-9._-]+"),        # JWT
            re.compile(
                r"\b(password|passwd|secret|token|api[\s_-]?key|access[\s_-]?token|credential)\s*[:=]\s*\S+",
                re.IGNORECASE,
            ),
            re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE),
            re.compile(r"\b(my|our|the)\s+(password|passwd|secret|api[\s_-]?key|access[\s_-]?token)\s+(is|:|=)\s*\S+", re.IGNORECASE),
        ]

        # Dangerous shell patterns (basic)
        self._dangerous_shell = [
            re.compile(r"rm\s+-rf"),
            re.compile(r"format\s+[a-z]:", re.IGNORECASE),
            re.compile(r"mkfs", re.IGNORECASE),
        ]

    def validate(self, record: MemoryRecord) -> ValidationResult:
        content_validation = self.validate_content(record.content)
        if not content_validation.allowed:
            return content_validation

        if not isinstance(record.metadata, dict) or len(record.metadata) > self.max_metadata_keys:
            return ValidationResult(False, "metadata_overflow")
        if not isinstance(record.id, str) or not record.id.strip() or not isinstance(record.source, str):
            return ValidationResult(False, "invalid_record_fields")
        if not isinstance(record.type, MemoryType) or not isinstance(record.explicit_user_approved, bool):
            return ValidationResult(False, "invalid_record_fields")
        if record.type == MemoryType.APPROVED_FACT and not record.explicit_user_approved:
            return ValidationResult(False, "explicit_approval_required")
        if (
            not isinstance(record.created_at, (int, float))
            or not math.isfinite(record.created_at)
            or not isinstance(record.updated_at, (int, float))
            or not math.isfinite(record.updated_at)
        ):
            return ValidationResult(False, "invalid_record_fields")
        try:
            json.dumps(record.metadata)
        except (TypeError, ValueError):
            return ValidationResult(False, "invalid_metadata")
        if not isinstance(record.confidence, (int, float)) or not math.isfinite(record.confidence) or not 0.0 <= record.confidence <= 1.0:
            return ValidationResult(False, "invalid_confidence")

        for value in self._text_values((record.id, record.source, record.metadata)):
            if self._matches_any(value, self._forbidden_patterns):
                return ValidationResult(False, "forbidden_pattern_detected")
            if self._matches_any(value, self._dangerous_shell):
                return ValidationResult(False, "dangerous_pattern_detected")

        return ValidationResult(True)

    def validate_content(self, content: object) -> ValidationResult:
        if not isinstance(content, str) or not content.strip() or len(content) > self.max_content_length:
            length = len(content) if isinstance(content, str) else 0
            return ValidationResult(False, f"content_length_violation: {length}")
        if self._matches_any(content, self._forbidden_patterns):
            return ValidationResult(False, "forbidden_pattern_detected")
        if self._matches_any(content, self._dangerous_shell):
            return ValidationResult(False, "dangerous_pattern_detected")
        return ValidationResult(True)

    @staticmethod
    def _text_values(value: object):
        if isinstance(value, str):
            yield value
        elif isinstance(value, dict):
            for key, nested in value.items():
                yield from MemoryValidator._text_values(key)
                yield from MemoryValidator._text_values(nested)
        elif isinstance(value, (list, tuple)):
            for nested in value:
                yield from MemoryValidator._text_values(nested)

    @staticmethod
    def _matches_any(value: str, patterns: list[re.Pattern[str]]) -> bool:
        return any(pattern.search(value) for pattern in patterns)
