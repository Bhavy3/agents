import pytest
from core.tools.n8n_tools import N8nTools
from core.tools.tool_registry import ToolRegistry
from core.tools.capability_loader import CapabilityLoader
from core.tools.verification import EffectVerifier

@pytest.mark.asyncio
async def test_n8n_tools_missing_key_behavior(monkeypatch):
    monkeypatch.delenv("N8N_API_KEY", raising=False)
    monkeypatch.setattr("core.security.credentials.keyring.get_password", lambda svc, key: None)
    # A real key can live in .env. Isolate the tool from every credential
    # source, otherwise this unit test creates a workflow on the live n8n.
    monkeypatch.setattr("core.tools.n8n_tools.get_secret", lambda name: None)
    tools = N8nTools()
    res = await tools.create_workflow("test_wf")
    assert res.success is False
    assert "missing" in res.error.lower()
    assert res.metadata["status_code"] == 401


def test_get_secret_keyring_fallback(monkeypatch):
    from core.security.credentials import get_secret

    monkeypatch.delenv("TEST_FRIDAY_SECRET", raising=False)
    monkeypatch.setattr(
        "core.security.credentials.keyring.get_password",
        lambda svc, key: "vault_secret_999" if key == "TEST_FRIDAY_SECRET" else None,
    )
    val = get_secret("TEST_FRIDAY_SECRET")
    assert val == "vault_secret_999"

@pytest.mark.asyncio
async def test_n8n_tools_verification_integration():
    loader = CapabilityLoader()
    caps = loader.load_all()
    assert "n8n_create_workflow" in caps
    assert "n8n_list_workflows" in caps

    cap = caps["n8n_create_workflow"]
    assert cap.verify.type == "http_ok"
    # n8n answers 201 Created; 200 is accepted for proxies in front of it.
    assert sorted(cap.verify.expect) == [200, 201]

    verifier = EffectVerifier()
    from core.tools.tool_models import ToolResult

    # Mock tool result from honest execution
    fake_success = ToolResult(True, "Created", metadata={"status_code": 200, "workflow_id": "wf_123"})
    outcome = verifier.verify(cap, {"name": "test_wf"}, fake_success)
    assert outcome.verified is True

    fake_failure = ToolResult(False, "", "Unauthorized", metadata={"status_code": 401})
    outcome_fail = verifier.verify(cap, {"name": "test_wf"}, fake_failure)
    assert outcome_fail.verified is False
    assert "HTTP 401" in outcome_fail.detail
