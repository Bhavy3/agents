import re
from typing import NamedTuple
from core.memory.memory_models import MemoryRecord


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
            re.compile(r"-----BEGIN [A-Z ]+ PRIVATE KEY-----"),
            re.compile(r"eyJ[a-zA-Z0-9._-]+"),        # JWT
            re.compile(r"(password|passwd|secret|token|apikey)\s*[:=]\s*\S+", re.IGNORECASE),
        ]

        # Dangerous shell patterns (basic)
        self._dangerous_shell = [
            re.compile(r"rm\s+-rf"),
            re.compile(r"format\s+[a-z]:", re.IGNORECASE),
            re.compile(r"mkfs", re.IGNORECASE),
        ]

    def validate(self, record: MemoryRecord) -> ValidationResult:
        if not record.content or len(record.content) > self.max_content_length:
            return ValidationResult(False, f"content_length_violation: {len(record.content) if record.content else 0}")

        if len(record.metadata) > self.max_metadata_keys:
            return ValidationResult(False, "metadata_overflow")

        # Check for secrets
        for pattern in self._forbidden_patterns:
            if pattern.search(record.content):
                return ValidationResult(False, "forbidden_pattern_detected")

        # Check for shell danger
        for pattern in self._dangerous_shell:
            if pattern.search(record.content):
                return ValidationResult(False, "dangerous_pattern_detected")

        return ValidationResult(True)
