from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Skill:
    name: str
    path: Path
    instructions: str


class SkillLoader:
    """Load only the requested SKILL.md instead of bloating every prompt."""

    def __init__(self, root: str | None = None) -> None:
        self.root = Path(root or os.getenv("FRIDAY_SKILLS_DIR", "skills")).expanduser().resolve()

    def list_skills(self) -> list[str]:
        if not self.root.is_dir():
            return []
        return sorted(
            path.parent.name
            for path in self.root.glob("*/SKILL.md")
            if path.is_file()
        )

    def load(self, name: str, max_chars: int = 12_000) -> Skill | None:
        safe_name = Path(name).name
        path = self.root / safe_name / "SKILL.md"
        if not path.is_file():
            return None
        content = path.read_text(encoding="utf-8", errors="replace")[:max_chars]
        return Skill(safe_name, path, content)
