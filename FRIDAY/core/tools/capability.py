"""Declarative capability contracts.

A capability is *data*: what it does in the user's terms, how it is invoked,
how its effect is proven, and whether it may be retried.  The kernel executes
it.  Nothing here depends on which LLM is configured, so the same architecture
runs unchanged against a 3B test model or a much larger one.

Phase 1 scope: these contracts are descriptive and drive the planner prompt.
Enforcement (verification, retry, grants) is layered on in later phases, which
is why ``risk`` and ``verify`` are recorded now rather than inferred later.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Mapping

from .tool_models import ToolRisk

CAPABILITY_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
_PLACEHOLDER_RE = re.compile(r"\{([a-z][a-z0-9_]*)\}")

VERIFY_TYPES: frozenset[str] = frozenset(
    {"none", "exit_code", "json", "text_matches", "file_exists", "http_ok", "dom_has", "semantic"}
)

EXEC_KINDS: frozenset[str] = frozenset({"kernel", "python", "shell", "http"})

# Controlled vocabulary for the data domains a capability is allowed to touch.
# Machine-readable on purpose: coverage must never be inferred from prose, because
# a description that merely mentions "email" does not grant access to an inbox.
COVERAGE_TOKENS: frozenset[str] = frozenset(
    {
        "public_web",
        "workspace_files",
        "local_system",
        "desktop_apps",
        "browser_session",
        "user_memory",
        "clock",
        # Private domains: declaring one is a promise that a real integration exists.
        "email",
        "calendar",
        "messages",
        "media",
    }
)

MAX_IDEMPOTENCY_KEY_CHARS = 512


class CapabilityError(ValueError):
    """A manifest is structurally invalid and must not be loaded."""


@dataclass(frozen=True, slots=True)
class ParamSpec:
    name: str
    type: str = "string"
    required: bool = False
    default: Any = None
    description: str = ""

    def to_json_schema(self) -> dict[str, Any]:
        schema: dict[str, Any] = {"type": self.type}
        if self.description:
            schema["description"] = self.description
        if self.default is not None:
            schema["default"] = self.default
        return schema


@dataclass(frozen=True, slots=True)
class VerifySpec:
    """How to prove the action had the intended effect."""

    type: str = "none"
    expect: Any = None
    description: str = ""

    def validate(self) -> None:
        if self.type not in VERIFY_TYPES:
            raise CapabilityError(
                f"unknown verify type '{self.type}'; expected one of {sorted(VERIFY_TYPES)}"
            )


@dataclass(frozen=True, slots=True)
class Capability:
    name: str
    description: str
    risk: ToolRisk = ToolRisk.SAFE
    params: tuple[ParamSpec, ...] = ()
    verify: VerifySpec = VerifySpec()
    retry_safe: bool = False
    idempotency: str = ""
    exec_kind: str = "kernel"
    entry: str = ""
    undo: str = "none"
    # Data domains this capability actually reaches. Empty means "declares no
    # coverage", which is the honest default for an unknown or generic tool.
    covers: tuple[str, ...] = ()
    provenance: Mapping[str, Any] = field(default_factory=dict)

    # -- introspection ---------------------------------------------------- #
    def required_params(self) -> tuple[str, ...]:
        return tuple(sorted(p.name for p in self.params if p.required))

    def parameter_names(self) -> frozenset[str]:
        return frozenset(p.name for p in self.params)

    def prompt_line(self) -> str:
        """One compact line for the planner prompt."""
        required = self.required_params()
        signature = f"({', '.join(required)})" if required else "()"
        return f"- {self.name}{signature}: {self.description}"

    def idempotency_key(self, arguments: Mapping[str, Any] | None = None) -> str:
        """Stable key for de-duplicating one intent; never raises on bad args."""
        args = dict(arguments or {})

        def substitute(match: re.Match[str]) -> str:
            key = match.group(1)
            value = args.get(key)
            return "?" if value is None else str(value)

        template = self.idempotency or self.name
        key = _PLACEHOLDER_RE.sub(substitute, template)
        return key[:MAX_IDEMPOTENCY_KEY_CHARS]

    def to_tool_schema(self) -> dict[str, Any]:
        """OpenAI-style function schema; usable for grammar/constraint too."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {p.name: p.to_json_schema() for p in self.params},
                "required": list(self.required_params()),
                "additionalProperties": True,
            },
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "risk": str(self.risk),
            "params": {
                p.name: {
                    "type": p.type,
                    "required": p.required,
                    "default": p.default,
                    "description": p.description,
                }
                for p in self.params
            },
            "verify": {
                "type": self.verify.type,
                "expect": self.verify.expect,
                "description": self.verify.description,
            },
            "retry_safe": self.retry_safe,
            "idempotency": self.idempotency,
            "exec": {"kind": self.exec_kind, "entry": self.entry},
            "undo": self.undo,
            "covers": list(self.covers),
            "provenance": dict(self.provenance),
        }

    # -- construction ----------------------------------------------------- #
    @classmethod
    def from_dict(cls, payload: Mapping[str, Any], source: str = "<memory>") -> "Capability":
        if not isinstance(payload, Mapping):
            raise CapabilityError(f"{source}: capability must be a mapping")

        name = str(payload.get("name", "")).strip()
        if not CAPABILITY_NAME_RE.match(name):
            raise CapabilityError(
                f"{source}: invalid capability name {name!r}; "
                "expected lowercase letters, digits and underscores"
            )

        description = " ".join(str(payload.get("description", "")).split())
        if not description:
            raise CapabilityError(f"{source}: capability '{name}' needs a description")
        if len(description) > 300:
            raise CapabilityError(
                f"{source}: capability '{name}' description is {len(description)} chars; "
                "keep it under 300 so prompts stay small"
            )

        risk_raw = str(payload.get("risk", "SAFE")).strip().upper()
        try:
            risk = ToolRisk[risk_raw]
        except KeyError:
            raise CapabilityError(
                f"{source}: capability '{name}' has unknown risk {risk_raw!r}; "
                f"expected one of {[r.name for r in ToolRisk]}"
            ) from None

        params = _parse_params(payload.get("params") or {}, name=name, source=source)

        verify_raw = payload.get("verify") or {"type": "none"}
        if isinstance(verify_raw, str):
            verify = VerifySpec(type=verify_raw)
        elif isinstance(verify_raw, Mapping):
            verify = VerifySpec(
                type=str(verify_raw.get("type", "none")),
                expect=verify_raw.get("expect"),
                description=str(verify_raw.get("description", "")),
            )
        else:
            raise CapabilityError(f"{source}: capability '{name}' has an invalid verify block")
        verify.validate()

        exec_raw = payload.get("exec") or {}
        if isinstance(exec_raw, str):
            exec_kind, entry = exec_raw, ""
        elif isinstance(exec_raw, Mapping):
            exec_kind = str(exec_raw.get("kind", "kernel"))
            entry = str(exec_raw.get("entry", ""))
        else:
            raise CapabilityError(f"{source}: capability '{name}' has an invalid exec block")
        if exec_kind not in EXEC_KINDS:
            raise CapabilityError(
                f"{source}: capability '{name}' has unknown exec kind {exec_kind!r}; "
                f"expected one of {sorted(EXEC_KINDS)}"
            )
        if exec_kind in {"python", "shell"} and not entry:
            raise CapabilityError(
                f"{source}: capability '{name}' with exec kind '{exec_kind}' needs an entry"
            )

        retry_safe = payload.get("retry_safe", False)
        if not isinstance(retry_safe, bool):
            raise CapabilityError(f"{source}: capability '{name}' retry_safe must be a boolean")

        idempotency = str(payload.get("idempotency", "") or "")
        unknown = [
            key for key in _PLACEHOLDER_RE.findall(idempotency)
            if key not in {p.name for p in params}
        ]
        if unknown:
            raise CapabilityError(
                f"{source}: capability '{name}' idempotency template references "
                f"undeclared parameter(s): {', '.join(sorted(set(unknown)))}"
            )

        raw_covers = payload.get("covers") or ()
        if isinstance(raw_covers, str):
            raw_covers = [raw_covers]
        covers = tuple(sorted({str(item).strip().lower() for item in raw_covers if str(item).strip()}))
        unknown_coverage = [token for token in covers if token not in COVERAGE_TOKENS]
        if unknown_coverage:
            raise CapabilityError(
                f"{source}: capability '{name}' declares unknown coverage "
                f"{unknown_coverage}; expected tokens from {sorted(COVERAGE_TOKENS)}"
            )

        return cls(
            name=name,
            description=description,
            risk=risk,
            params=params,
            verify=verify,
            retry_safe=retry_safe,
            idempotency=idempotency,
            exec_kind=exec_kind,
            entry=entry,
            undo=str(payload.get("undo", "none") or "none"),
            covers=covers,
            provenance=dict(payload.get("provenance") or {"source": source}),
        )


def _parse_params(raw: Any, *, name: str, source: str) -> tuple[ParamSpec, ...]:
    entries: list[ParamSpec] = []

    if isinstance(raw, Mapping):
        for param_name, spec in raw.items():
            if not CAPABILITY_NAME_RE.match(str(param_name)):
                raise CapabilityError(
                    f"{source}: capability '{name}' has invalid parameter name {param_name!r}"
                )
            if isinstance(spec, Mapping):
                entries.append(
                    ParamSpec(
                        name=str(param_name),
                        type=str(spec.get("type", "string")),
                        required=bool(spec.get("required", False)),
                        default=spec.get("default"),
                        description=str(spec.get("description", "")),
                    )
                )
            else:
                entries.append(ParamSpec(name=str(param_name), type=str(spec)))
    elif isinstance(raw, list):
        for spec in raw:
            if not isinstance(spec, Mapping) or "name" not in spec:
                raise CapabilityError(
                    f"{source}: capability '{name}' list parameters must be mappings with a name"
                )
            entries.append(
                ParamSpec(
                    name=str(spec["name"]),
                    type=str(spec.get("type", "string")),
                    required=bool(spec.get("required", False)),
                    default=spec.get("default"),
                    description=str(spec.get("description", "")),
                )
            )
    else:
        raise CapabilityError(f"{source}: capability '{name}' params must be a mapping or list")

    seen: set[str] = set()
    for entry in entries:
        if entry.name in seen:
            raise CapabilityError(
                f"{source}: capability '{name}' declares duplicate parameter '{entry.name}'"
            )
        seen.add(entry.name)
    return tuple(entries)
