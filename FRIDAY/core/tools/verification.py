"""Verify the effect of an action, not the tool's claim about it.

The kernel previously trusted ``ToolResult.success``.  A tool that returned
success without doing anything was reported to the user as a completed action.
This module checks the observable world against the capability contract.

Honesty rule: verification is only *enforced* when the evidence actually
exists.  When a contract declares a check whose evidence the tool did not
supply, the outcome is "unchecked" with a reason - it never fabricates a pass
and never fabricates a failure it cannot justify.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from ..logging.logger import get_logger
from .capability import Capability, VerifySpec
from .tool_models import ToolResult


@dataclass(frozen=True, slots=True)
class VerificationOutcome:
    """Result of checking one action's declared effect."""

    checked: bool
    passed: bool
    detail: str

    @property
    def verified(self) -> bool:
        return self.checked and self.passed


class EffectVerifier:
    """Evaluates a capability's ``verify`` spec against real evidence."""

    def __init__(self, workspace_root: str | None = None) -> None:
        configured = workspace_root or os.getenv("FRIDAY_WORKSPACE_ROOT") or os.getcwd()
        self.workspace_root = Path(configured).expanduser().resolve()
        self.logger = get_logger("tools.verification")

    def verify(
        self,
        capability: Capability | None,
        arguments: Mapping[str, Any] | None,
        result: ToolResult,
    ) -> VerificationOutcome:
        if capability is None:
            return VerificationOutcome(False, bool(result.success), "no capability contract")

        spec = capability.verify
        if spec.type == "none":
            return VerificationOutcome(False, bool(result.success), "no verification declared")

        if spec.type == "file_exists":
            return self._file_exists(spec, arguments or {}, result)
        if spec.type == "exit_code":
            return self._exit_code(spec, result)
        if spec.type in {"text_matches", "dom_has"}:
            return self._text_matches(spec, result)
        if spec.type == "json":
            return self._json(spec, result)
        if spec.type == "http_ok":
            return self._http_ok(spec, result)
        if spec.type == "semantic":
            return self._semantic(spec, arguments or {}, result)

        # VerifySpec.validate() rejects unknown types at load time; reaching here
        # means the manifest was constructed in code. Do not claim success.
        return VerificationOutcome(False, bool(result.success), f"unsupported verify type {spec.type!r}")

    # -- individual checks -------------------------------------------------- #
    def _file_exists(
        self, spec: VerifySpec, arguments: Mapping[str, Any], result: ToolResult
    ) -> VerificationOutcome:
        raw_name = str(spec.expect or "file_path")
        raw_value = str(arguments.get(raw_name, "") or "").strip()
        if not raw_value:
            return VerificationOutcome(True, False, f"verification failed: no '{raw_name}' argument")
        if not result.success:
            return VerificationOutcome(
                True, False, f"action failed before verification: {result.error or 'unknown error'}"
            )
        try:
            path = self._resolve_inside_workspace(raw_value)
        except ValueError as exc:
            return VerificationOutcome(True, False, f"verification failed: {exc}")
        if path.is_file():
            try:
                size = path.stat().st_size
            except OSError:
                size = -1
            return VerificationOutcome(True, True, f"verified: {raw_value} exists ({size} bytes)")
        return VerificationOutcome(True, False, f"verification failed: {raw_value} does not exist")

    def _exit_code(self, spec: VerifySpec, result: ToolResult) -> VerificationOutcome:
        declared = (result.metadata or {}).get("exit_code")
        if declared is None:
            # The tool cannot prove how it exited; do not pretend we checked.
            return VerificationOutcome(
                False, bool(result.success), "tool did not report an exit code; cannot verify"
            )
        expected = 0 if spec.expect is None else int(spec.expect)
        try:
            actual = int(declared)
        except (TypeError, ValueError):
            return VerificationOutcome(True, False, f"verification failed: unreadable exit code {declared!r}")
        if actual == expected:
            return VerificationOutcome(True, True, f"verified: exit code {actual}")
        return VerificationOutcome(True, False, f"verification failed: exit code {actual}, expected {expected}")

    def _text_matches(self, spec: VerifySpec, result: ToolResult) -> VerificationOutcome:
        pattern = str(spec.expect or "").strip()
        if not pattern:
            return VerificationOutcome(False, bool(result.success), "no expected text declared")
        if not result.success:
            return VerificationOutcome(
                True, False, f"action failed before verification: {result.error or 'unknown error'}"
            )
        if re.search(pattern, result.output or "", re.IGNORECASE):
            return VerificationOutcome(True, True, f"verified: output matches {pattern!r}")
        return VerificationOutcome(True, False, f"verification failed: output missing {pattern!r}")

    def _json(self, spec: VerifySpec, result: ToolResult) -> VerificationOutcome:
        if not result.success:
            return VerificationOutcome(
                True, False, f"action failed before verification: {result.error or 'unknown error'}"
            )
        try:
            parsed = json.loads(result.output or "")
        except (json.JSONDecodeError, TypeError) as exc:
            return VerificationOutcome(True, False, f"verification failed: output is not JSON ({exc})")
        if isinstance(spec.expect, Mapping):
            mismatched = [
                key for key, expected in spec.expect.items()
                if parsed.get(key) != expected if isinstance(parsed, Mapping)
            ]
            if mismatched:
                return VerificationOutcome(
                    True, False, f"verification failed: unexpected {', '.join(mismatched)}"
                )
        return VerificationOutcome(True, True, "verified: output parsed as expected JSON")

    def _http_ok(self, spec: VerifySpec, result: ToolResult) -> VerificationOutcome:
        status = (result.metadata or {}).get("status_code")
        if status is None:
            return VerificationOutcome(
                False, bool(result.success), "tool did not report an HTTP status; cannot verify"
            )
        try:
            actual = int(status)
        except (TypeError, ValueError):
            return VerificationOutcome(
                True, False, f"verification failed: unreadable HTTP status {status!r}"
            )

        if spec.expect is None:
            # "http_ok" means the request succeeded, not one exact code.
            ok = 200 <= actual < 300
            wanted = "2xx"
        elif isinstance(spec.expect, (list, tuple, set, frozenset)):
            accepted = [int(value) for value in spec.expect]
            ok = actual in accepted
            wanted = "/".join(str(value) for value in accepted)
        else:
            expected = int(spec.expect)
            ok = actual == expected
            wanted = str(expected)

        if ok:
            return VerificationOutcome(True, True, f"verified: HTTP {actual}")
        return VerificationOutcome(
            True, False, f"verification failed: HTTP {actual}, expected {wanted}"
        )

    def _semantic(
        self, spec: VerifySpec, arguments: Mapping[str, Any], result: ToolResult
    ) -> VerificationOutcome:
        if not result.success:
            return VerificationOutcome(
                True, False, f"action failed before verification: {result.error or 'unknown error'}"
            )
        metadata = result.metadata or {}
        if "goal_met" in metadata:
            met = bool(metadata["goal_met"])
            if met:
                return VerificationOutcome(True, True, "verified: goal was met")
            return VerificationOutcome(
                True, False, f"verification failed: goal was not met ({result.error or 'criteria unfulfilled'})"
            )

        expected = str(spec.expect or arguments.get("expected") or arguments.get("goal") or "").strip()
        if not expected:
            return VerificationOutcome(
                False, bool(result.success), "no expected criteria or goal_met evidence provided"
            )

        output_str = str(result.output or "").strip()
        output_lower = output_str.casefold()
        expected_lower = expected.casefold()

        # Semantic Negation and Contradiction Detection
        negation_markers = [
            f"not {expected_lower}",
            f"failed to {expected_lower}",
            f"cannot {expected_lower}",
            f"unable to {expected_lower}",
            f"could not {expected_lower}",
            f"did not {expected_lower}",
            f"unsuccessful {expected_lower}",
        ]
        if any(marker in output_lower for marker in negation_markers):
            return VerificationOutcome(
                True, False, f"verification failed: output expresses negation of {expected!r}"
            )

        # Check for general failure indicators when expected is an affirmative success state
        if any(term in expected_lower for term in ("success", "pass", "green", "complete", "ok")):
            failure_cues = ["failed", "failure", "error:", "exception:", "crashed", "0 passed"]
            if any(cue in output_lower for cue in failure_cues) and "0 failed" not in output_lower and "0 errors" not in output_lower:
                return VerificationOutcome(
                    True, False, f"verification failed: output did not satisfy semantic expectation, contains contradictory failure cues for {expected!r}"
                )

        if expected_lower in output_lower:
            return VerificationOutcome(True, True, f"verified: output satisfies semantic expectation {expected!r}")

        return VerificationOutcome(
            True, False, f"verification failed: output did not satisfy semantic expectation {expected!r}"
        )

    # -- helpers ------------------------------------------------------------ #
    def _resolve_inside_workspace(self, raw: str) -> Path:
        if raw.startswith("\\\\") or raw.startswith("//"):
            raise ValueError(f"UNC and device paths are not allowed: {raw}")
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            candidate = self.workspace_root / candidate
        candidate = candidate.resolve()
        if candidate != self.workspace_root and self.workspace_root not in candidate.parents:
            raise ValueError(f"path '{raw}' escapes FRIDAY_WORKSPACE_ROOT")
        return candidate
