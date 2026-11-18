"""Effect verification: prove the world changed, not that a tool said so."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from core.tools.capability import Capability
from core.tools.tool_models import ToolResult, ToolRisk
from core.tools.tool_worker import ToolWorker
from core.tools.verification import EffectVerifier


def _cap(**overrides: Any) -> Capability:
    payload: dict[str, Any] = {"name": "sample_tool", "description": "does a sample thing"}
    payload.update(overrides)
    return Capability.from_dict(payload)


class _StubBus:
    _running = True

    def __init__(self) -> None:
        self.events: list[Any] = []

    async def publish(self, event: Any) -> None:
        self.events.append(event)

    def subscribe(self, *args: Any, **kwargs: Any) -> None:
        return None


# --- verifier units -------------------------------------------------------- #
def test_undeclared_verification_is_unchecked_not_passed():
    outcome = EffectVerifier().verify(_cap(), {}, ToolResult(True, "ok"))
    assert outcome.checked is False
    assert outcome.verified is False


def test_file_exists_passes_only_when_the_file_is_on_disk(tmp_path):
    verifier = EffectVerifier(str(tmp_path))
    capability = _cap(verify={"type": "file_exists", "expect": "file_path"})
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")

    present = verifier.verify(capability, {"file_path": "a.txt"}, ToolResult(True, "wrote"))
    absent = verifier.verify(capability, {"file_path": "b.txt"}, ToolResult(True, "wrote"))

    assert present.checked and present.passed
    assert absent.checked and not absent.passed


def test_file_exists_rejects_a_path_that_escapes_the_workspace(tmp_path):
    verifier = EffectVerifier(str(tmp_path))
    capability = _cap(verify={"type": "file_exists", "expect": "file_path"})
    outcome = verifier.verify(capability, {"file_path": "../outside.txt"}, ToolResult(True, "wrote"))
    assert outcome.checked and not outcome.passed
    assert "escapes" in outcome.detail


def test_file_exists_fails_when_the_action_itself_failed(tmp_path):
    verifier = EffectVerifier(str(tmp_path))
    capability = _cap(verify={"type": "file_exists", "expect": "file_path"})
    outcome = verifier.verify(capability, {"file_path": "a.txt"}, ToolResult(False, "", "denied"))
    assert outcome.checked and not outcome.passed


def test_exit_code_pass_and_fail():
    verifier = EffectVerifier()
    capability = _cap(verify={"type": "exit_code", "expect": 0})

    good = verifier.verify(capability, {}, ToolResult(True, "ok", metadata={"exit_code": 0}))
    bad = verifier.verify(capability, {}, ToolResult(False, "", "exit code 3", metadata={"exit_code": 3}))

    assert good.checked and good.passed
    assert bad.checked and not bad.passed


def test_exit_code_without_evidence_is_never_claimed_as_verified():
    verifier = EffectVerifier()
    capability = _cap(verify={"type": "exit_code", "expect": 0})
    outcome = verifier.verify(capability, {}, ToolResult(True, "ok"))
    assert outcome.checked is False
    assert "cannot verify" in outcome.detail


def test_text_matches():
    verifier = EffectVerifier()
    capability = _cap(verify={"type": "text_matches", "expect": "needle"})
    assert verifier.verify(capability, {}, ToolResult(True, "a needle here")).passed
    assert not verifier.verify(capability, {}, ToolResult(True, "nothing here")).passed


def test_json_verification():
    verifier = EffectVerifier()
    capability = _cap(verify={"type": "json", "expect": {"ok": True}})
    assert verifier.verify(capability, {}, ToolResult(True, json.dumps({"ok": True}))).passed
    assert not verifier.verify(capability, {}, ToolResult(True, "not json")).passed


def test_http_without_status_is_unchecked():
    verifier = EffectVerifier()
    capability = _cap(verify={"type": "http_ok"})
    outcome = verifier.verify(capability, {}, ToolResult(True, "opened"))
    assert outcome.checked is False


def test_http_ok_accepts_any_2xx_when_no_code_is_declared():
    verifier = EffectVerifier()
    capability = _cap(verify={"type": "http_ok"})
    assert verifier.verify(capability, {}, ToolResult(True, "", metadata={"status_code": 204})).passed
    assert not verifier.verify(capability, {}, ToolResult(False, "", metadata={"status_code": 500})).passed


def test_http_ok_accepts_a_list_of_codes():
    """n8n answers 201 Created, so a single expected 200 would reject success."""
    verifier = EffectVerifier()
    capability = _cap(verify={"type": "http_ok", "expect": [200, 201]})
    assert verifier.verify(capability, {}, ToolResult(True, "", metadata={"status_code": 201})).passed
    assert verifier.verify(capability, {}, ToolResult(True, "", metadata={"status_code": 200})).passed
    assert not verifier.verify(capability, {}, ToolResult(False, "", metadata={"status_code": 401})).passed


# --- kernel wiring --------------------------------------------------------- #
def test_worker_catches_a_tool_that_lies_about_writing(tmp_path, monkeypatch):
    monkeypatch.setenv("FRIDAY_WORKSPACE_ROOT", str(tmp_path))
    worker = ToolWorker(_StubBus())

    async def liar(**kwargs: Any) -> ToolResult:
        return ToolResult(True, "Wrote it successfully!")

    worker.registry.register("write_text_file", liar)
    result = asyncio.run(
        worker.execute_tool(
            "write_text_file", {"file_path": "ghost.txt", "content": "x"}, "corr", ToolRisk.RESTRICTED
        )
    )

    assert result.success is False
    assert "verification failed" in (result.error or "")
    assert not (tmp_path / "ghost.txt").exists()
    assert worker.audit_log[-1].verified is False


def test_worker_marks_a_real_write_as_verified(tmp_path, monkeypatch):
    monkeypatch.setenv("FRIDAY_WORKSPACE_ROOT", str(tmp_path))
    worker = ToolWorker(_StubBus())

    result = asyncio.run(
        worker.execute_tool(
            "write_text_file", {"file_path": "real.txt", "content": "data"}, "corr", ToolRisk.RESTRICTED
        )
    )

    assert result.success is True
    assert (tmp_path / "real.txt").read_text(encoding="utf-8") == "data"
    assert worker.audit_log[-1].verified is True


def test_worker_reports_a_failed_command_as_failed(tmp_path, monkeypatch):
    monkeypatch.setenv("FRIDAY_WORKSPACE_ROOT", str(tmp_path))
    worker = ToolWorker(_StubBus())

    result = asyncio.run(
        worker.execute_tool("execute_shell", {"command": "exit 3"}, "corr", ToolRisk.DANGEROUS)
    )

    assert result.success is False
    assert result.metadata.get("exit_code") == 3
