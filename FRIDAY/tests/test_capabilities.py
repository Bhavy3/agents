"""Capability contracts: manifests are data, and they must stay in sync."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.tools.capability import Capability, CapabilityError
from core.tools.capability_loader import CapabilityLoader
from core.tools.tool_models import ToolRisk
from core.tools.tool_registry import ToolRegistry
from core.workflows.planner import _REQUIRED_PARAMETERS, BoundedPlanner

FRIDAY_ROOT = Path(__file__).resolve().parents[1]
CAPABILITIES_DIR = FRIDAY_ROOT / "capabilities"


def _load() -> dict[str, Capability]:
    return CapabilityLoader(CAPABILITIES_DIR).load_all()


def test_core_manifests_load_without_problems():
    loader = CapabilityLoader(CAPABILITIES_DIR)
    capabilities = loader.load_all()
    assert capabilities, "no capability manifests were loaded"
    assert loader.problems == [], f"manifest problems: {loader.problems}"


def test_every_registry_tool_has_a_capability_contract():
    registered = set(ToolRegistry().list_tools())
    described = set(_load())
    missing = sorted(registered - described)
    assert not missing, f"tools without a capability contract: {missing}"


def test_no_capability_contract_for_unknown_tool():
    registered = set(ToolRegistry().list_tools())
    extra = sorted(set(_load()) - registered)
    assert not extra, f"contracts for tools that do not exist: {extra}"


def test_required_parameters_match_the_planner_table():
    capabilities = _load()
    for name, expected in _REQUIRED_PARAMETERS.items():
        assert name in capabilities, f"missing contract for {name}"
        assert set(capabilities[name].required_params()) == expected, (
            f"{name}: manifest requires {capabilities[name].required_params()}, "
            f"planner enforces {sorted(expected)}"
        )


def test_shell_is_flagged_dangerous_and_not_retry_safe():
    shell = _load()["execute_shell"]
    assert shell.risk is ToolRisk.DANGEROUS
    assert shell.retry_safe is False
    assert shell.verify.type == "exit_code"


def test_public_web_capabilities_never_claim_private_data_access():
    capabilities = _load()
    for name in ("search_web", "research_web", "open_url"):
        description = capabilities[name].description.lower()
        assert "public" in description, f"{name} must state it is public-web only"
    assert "email" in capabilities["search_web"].description.lower()


def test_idempotency_key_is_stable_and_safe_on_missing_args():
    capability = Capability.from_dict(
        {
            "name": "sample_search",
            "description": "search something",
            "params": {"query": {"required": True}},
            "idempotency": "sample_search:{query}",
        }
    )
    assert capability.idempotency_key({"query": "a b"}) == "sample_search:a b"
    assert capability.idempotency_key({}) == "sample_search:?"


def test_tool_schema_exposes_required_parameters():
    schema = _load()["write_text_file"].to_tool_schema()
    assert schema["name"] == "write_text_file"
    assert sorted(schema["parameters"]["required"]) == ["content", "file_path"]
    assert set(schema["parameters"]["properties"]) == {"content", "file_path"}


def test_unknown_risk_is_rejected():
    with pytest.raises(CapabilityError, match="unknown risk"):
        Capability.from_dict({"name": "bad_risk", "description": "x", "risk": "EXTREME"})


def test_unknown_verify_type_is_rejected():
    with pytest.raises(CapabilityError, match="unknown verify type"):
        Capability.from_dict(
            {"name": "bad_verify", "description": "x", "verify": {"type": "telepathy"}}
        )


def test_idempotency_template_must_reference_declared_parameters():
    with pytest.raises(CapabilityError, match="undeclared parameter"):
        Capability.from_dict(
            {
                "name": "bad_key",
                "description": "x",
                "params": {"query": {"required": True}},
                "idempotency": "bad_key:{missing_arg}",
            }
        )


def test_description_is_required():
    with pytest.raises(CapabilityError, match="needs a description"):
        Capability.from_dict({"name": "no_desc", "description": "   "})


def test_a_broken_manifest_is_recorded_not_raised(tmp_path):
    (tmp_path / "broken.yaml").write_text(
        "good_one:\n  description: fine\nbad_one:\n  risk: SAFE\n", encoding="utf-8"
    )
    loader = CapabilityLoader(tmp_path)
    capabilities = loader.load_all()
    assert "good_one" in capabilities
    assert "bad_one" not in capabilities
    assert any(problem["capability"] == "bad_one" for problem in loader.problems)


def test_json_manifests_load(tmp_path):
    payload = {
        "capabilities": [
            {"name": "json_tool", "description": "a json declared capability", "risk": "SAFE"}
        ]
    }
    (tmp_path / "extra.json").write_text(json.dumps(payload), encoding="utf-8")
    capabilities = CapabilityLoader(tmp_path).load_all()
    assert set(capabilities) == {"json_tool"}


def test_duplicate_capability_across_files_is_reported(tmp_path):
    body = "dup_tool:\n  description: first\n"
    (tmp_path / "a.yaml").write_text(body, encoding="utf-8")
    (tmp_path / "b.yaml").write_text(
        "dup_tool:\n  description: second\n", encoding="utf-8"
    )
    loader = CapabilityLoader(tmp_path)
    capabilities = loader.load_all()
    assert len(capabilities) == 1
    assert any("duplicate capability name" in p["reason"] for p in loader.problems)


def test_planner_prompt_states_the_capability_domain_rule():
    """A 3B model must be told that public-web tools cannot read private data.

    Verbose per-tool descriptions were measured to make planning worse on a 3B,
    so the prompt carries one compact rule instead of 26 long lines.
    """
    planner = BoundedPlanner(ollama_client=object(), tool_registry=ToolRegistry())
    prompt = planner._build_prompt("do something unrelated")
    assert "Use each tool only within its stated domain" in prompt
    assert "private email" in prompt
    assert "return []" in prompt


def test_describe_returns_short_summaries_for_every_contract():
    described = CapabilityLoader(CAPABILITIES_DIR).describe(max_chars=60)
    assert set(described) == set(_load())
    for name, summary in described.items():
        assert summary, f"{name} has no summary"
        assert len(summary) <= 60, f"{name} summary is too long for a prompt"
        assert not summary.endswith(" "), f"{name} summary has trailing space"
