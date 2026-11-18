import pytest
from pathlib import Path

from core.skills.acquirer import CapabilityAcquirer, CapabilityAcquisitionError


def test_acquire_skill_creates_and_loads_skill(tmp_path):
    skills_dir = tmp_path / "skills"
    acquirer = CapabilityAcquirer(skills_root=str(skills_dir))

    skill = acquirer.acquire_skill("docker_deploy", "Build container and push to registry.")

    assert skill.name == "docker_deploy"
    assert "Build container" in skill.instructions
    assert (skills_dir / "docker_deploy" / "SKILL.md").is_file()

    # Verify SkillLoader can list and retrieve it
    assert "docker_deploy" in acquirer.skill_loader.list_skills()


def test_acquire_skill_rejects_empty_instructions(tmp_path):
    acquirer = CapabilityAcquirer(skills_root=str(tmp_path / "skills"))
    with pytest.raises(CapabilityAcquisitionError):
        acquirer.acquire_skill("bad_skill", "   ")


def test_acquire_capability_creates_and_reloads_manifest(tmp_path):
    caps_dir = tmp_path / "caps"
    acquirer = CapabilityAcquirer(capabilities_root=str(caps_dir))

    cap = acquirer.acquire_capability(
        name="custom_api_ping",
        description="Pings custom healthcheck endpoint",
        risk="SAFE",
        covers=["public_web"],
        verify_type="http_ok",
        verify_expect=200,
        retry_safe=True,
    )

    assert cap.name == "custom_api_ping"
    assert cap.verify.type == "http_ok"
    assert cap.retry_safe is True
    assert (caps_dir / "custom_api_ping.yaml").is_file()

    # Verify CapabilityLoader reloads it
    all_caps = acquirer.cap_loader.load_all()
    assert "custom_api_ping" in all_caps
    assert all_caps["custom_api_ping"].covers == ("public_web",)
