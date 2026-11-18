"""Autonomous capability & skill acquisition for FRIDAY (Phase 7).

Allows the agent to self-author new skills and declare capability manifests
at runtime, validating them before persistence and dynamic loading.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml

from ..tools.capability import Capability, ToolRisk, VerifySpec
from ..tools.capability_loader import CapabilityLoader
from .loader import Skill, SkillLoader

_SAFE_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{1,63}$")


class CapabilityAcquisitionError(ValueError):
    """Raised when an acquired skill or capability fails validation."""


class CapabilityAcquirer:
    """Manages the autonomous discovery, creation, and registration of new skills and capabilities."""

    def __init__(
        self,
        skills_root: str | None = None,
        capabilities_root: str | None = None,
    ) -> None:
        configured_skills = skills_root or os.getenv("FRIDAY_SKILLS_DIR", "skills")
        self.skills_root = Path(configured_skills).expanduser().resolve()
        configured_caps = capabilities_root or os.getenv("FRIDAY_CAPABILITIES_DIR", "capabilities")
        self.capabilities_root = Path(configured_caps).expanduser().resolve()

        self.skill_loader = SkillLoader(str(self.skills_root))
        self.cap_loader = CapabilityLoader(str(self.capabilities_root))

    def acquire_skill(self, name: str, instructions: str) -> Skill:
        """Create and register a new persistent skill document."""
        clean_name = name.strip().casefold()
        if not _SAFE_NAME_RE.match(clean_name):
            raise CapabilityAcquisitionError(f"Invalid skill name '{name}'; must be alphanumeric/dashes")

        clean_instructions = str(instructions or "").strip()
        if not clean_instructions:
            raise CapabilityAcquisitionError("Skill instructions cannot be empty")

        skill_dir = self.skills_root / clean_name
        skill_dir.mkdir(parents=True, exist_ok=True)
        skill_file = skill_dir / "SKILL.md"
        skill_file.write_text(clean_instructions, encoding="utf-8")

        loaded = self.skill_loader.load(clean_name)
        if not loaded:
            raise CapabilityAcquisitionError(f"Failed to load acquired skill '{clean_name}' after writing")

        return loaded

    async def learn_skill_from_tutorial(
        self,
        skill_name: str,
        tutorial_content: str,
        llm_client: Any = None,
    ) -> Skill:
        """Synthesize operational skill instructions from tutorial/doc content and register it."""
        if not tutorial_content.strip():
            raise CapabilityAcquisitionError("Tutorial content is empty")

        instructions = ""
        if llm_client is not None:
            prompt = (
                f"You are FRIDAY's Autonomous Skill Synthesis Engine.\n"
                f"Extract and author a structured SKILL.md document from the following tutorial/transcript content.\n"
                f"Target skill name: {skill_name}\n\n"
                f"Tutorial Raw Content:\n{tutorial_content[:4000]}\n\n"
                f"Output MUST be valid markdown containing:\n"
                f"# {skill_name}\n"
                f"## Purpose\n"
                f"## Execution Steps\n"
                f"## Constraints & Verifications\n\n"
                f"Markdown:"
            )
            response, metrics = await llm_client.generate(prompt, max_tokens=600)
            if metrics.success and response and len(response.strip()) > 50:
                instructions = response.strip()

        if not instructions:
            instructions = (
                f"# {skill_name}\n\n"
                f"## Purpose\nOperational skill synthesized from tutorial.\n\n"
                f"## Execution Steps\n{tutorial_content.strip()[:1500]}\n\n"
                f"## Constraints\n- Public web only\n- Confined to workspace\n"
            )

        return self.acquire_skill(skill_name, instructions)

    async def learn_skill_from_youtube_url(
        self,
        skill_name: str,
        youtube_url: str,
        llm_client: Any = None,
    ) -> Skill:
        """Fetch transcript from a live YouTube URL, extract actionable steps, and register the skill."""
        match = re.search(r"(?:v=|\/)([0-9A-Za-z_-]{11})", youtube_url)
        video_id = match.group(1) if match else youtube_url.strip()

        try:
            from youtube_transcript_api import YouTubeTranscriptApi
            api = YouTubeTranscriptApi()
            transcript = api.fetch(video_id)
            full_transcript_text = " ".join(getattr(snippet, "text", str(snippet)) for snippet in transcript)
        except Exception as e:
            raise CapabilityAcquisitionError(f"Failed to fetch YouTube transcript for '{youtube_url}': {e}") from e

        return await self.learn_skill_from_tutorial(
            skill_name=skill_name,
            tutorial_content=full_transcript_text[:4000],
            llm_client=llm_client,
        )

    def acquire_capability(
        self,
        name: str,
        description: str,
        risk: str = "SAFE",
        covers: list[str] | None = None,
        verify_type: str = "none",
        verify_expect: Any = None,
        retry_safe: bool = False,
        params: dict[str, Any] | None = None,
    ) -> Capability:
        """Persist and dynamically register a new capability contract."""
        clean_name = name.strip().casefold()
        if not _SAFE_NAME_RE.match(clean_name):
            raise CapabilityAcquisitionError(f"Invalid capability name '{name}'")

        raw_payload = {
            "description": description.strip(),
            "risk": risk.upper(),
            "covers": covers or ["local_system"],
            "verify": {"type": verify_type, "expect": verify_expect},
            "retry_safe": bool(retry_safe),
            "params": params or {},
        }

        # Validate with Capability.from_dict before writing to disk
        cap = Capability.from_dict({"name": clean_name, **raw_payload}, source=f"acquired_{clean_name}")

        self.capabilities_root.mkdir(parents=True, exist_ok=True)
        manifest_file = self.capabilities_root / f"{clean_name}.yaml"
        manifest_content = yaml.dump({clean_name: raw_payload}, sort_keys=False)
        manifest_file.write_text(manifest_content, encoding="utf-8")

        # Verify loader recognizes the new capability
        reloaded = self.cap_loader.load_all()
        if clean_name not in reloaded:
            raise CapabilityAcquisitionError(f"Capability '{clean_name}' written but not loadable")

        return cap
