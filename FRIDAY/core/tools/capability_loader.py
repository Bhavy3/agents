"""Load capability manifests from disk.

Capabilities are data, so adding one is writing a file, not editing the kernel.
A malformed manifest must never take the application down: problems are
collected and logged at ERROR with the file and the reason, and the remaining
manifests still load.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping

from ..logging.logger import get_logger
from .capability import Capability, CapabilityError

try:  # optional: manifests may be JSON if PyYAML is unavailable
    import yaml
except ImportError:  # pragma: no cover - exercised only without PyYAML
    yaml = None  # type: ignore[assignment]

MANIFEST_SUFFIXES = (".yaml", ".yml", ".json")
MAX_DESCRIPTION_PROMPT_CHARS = 120


class CapabilityLoader:
    """Discovers and validates capability manifests under a root directory."""

    def __init__(self, root: str | Path | None = None) -> None:
        default_root = Path(__file__).resolve().parents[2] / "capabilities"
        configured = root or os.getenv("FRIDAY_CAPABILITIES_DIR") or default_root
        self.root = Path(configured).expanduser()
        self.logger = get_logger("tools.capabilities")
        self._problems: list[dict[str, str]] = []

    # -- public ------------------------------------------------------------ #
    @property
    def problems(self) -> list[dict[str, str]]:
        return list(self._problems)

    def manifest_paths(self) -> list[Path]:
        if not self.root.is_dir():
            return []
        return sorted(
            path
            for path in self.root.iterdir()
            if path.is_file() and path.suffix.lower() in MANIFEST_SUFFIXES
        )

    def load_all(self) -> dict[str, Capability]:
        """Return every valid capability, keyed by name. Never raises."""
        self._problems = []
        capabilities: dict[str, Capability] = {}
        for path in self.manifest_paths():
            for capability in self.load_file(path):
                existing = capabilities.get(capability.name)
                if existing is not None:
                    self._record(
                        path,
                        capability.name,
                        f"duplicate capability name (already defined by "
                        f"{existing.provenance.get('source', 'another manifest')})",
                    )
                    continue
                capabilities[capability.name] = capability
        return capabilities

    def load_file(self, path: str | Path) -> list[Capability]:
        file_path = Path(path)
        payload = self._read(file_path)
        if payload is None:
            return []

        capabilities: list[Capability] = []
        for name, spec in _iter_manifest_entries(payload):
            if not isinstance(spec, Mapping):
                self._record(file_path, name, "manifest entry must be a mapping")
                continue
            entry = dict(spec)
            entry.setdefault("name", name)
            try:
                capabilities.append(
                    Capability.from_dict(entry, source=file_path.name)
                )
            except CapabilityError as exc:
                self._record(file_path, str(entry.get("name", name)), str(exc))
            except Exception as exc:  # never let one manifest break startup
                self.logger.exception("capability_manifest_unexpected_error")
                self._record(file_path, str(entry.get("name", name)), repr(exc))
        return capabilities

    def describe(self, max_chars: int = MAX_DESCRIPTION_PROMPT_CHARS) -> dict[str, str]:
        """name -> short description, for planner prompt injection."""
        described: dict[str, str] = {}
        for name, capability in self.load_all().items():
            text = capability.description
            if len(text) > max_chars:
                # Cut on a word boundary: a severed word costs the model meaning.
                cut = text[: max_chars - 1]
                if " " in cut:
                    cut = cut[: cut.rfind(" ")]
                text = cut.rstrip(" ,;:.") + "…"
            described[name] = text
        return described

    # -- internals --------------------------------------------------------- #
    def _read(self, path: Path) -> Any | None:
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError as exc:
            self._record(path, "-", f"cannot read manifest: {exc}")
            return None

        if path.suffix.lower() == ".json":
            try:
                return json.loads(raw)
            except json.JSONDecodeError as exc:
                self._record(path, "-", f"invalid JSON: {exc}")
                return None

        if yaml is None:
            self._record(path, "-", "PyYAML is not installed; cannot read YAML manifests")
            return None
        try:
            return yaml.safe_load(raw)
        except yaml.YAMLError as exc:  # type: ignore[attr-defined]
            self._record(path, "-", f"invalid YAML: {exc}")
            return None

    def _record(self, path: Path, name: str, reason: str) -> None:
        problem = {"file": path.name, "capability": name, "reason": reason}
        self._problems.append(problem)
        self.logger.error(
            "capability_manifest_rejected",
            extra={"file": path.name, "capability": name, "reason": reason},
        )


def _iter_manifest_entries(payload: Any):
    """Accept a mapping of name->spec, a list of specs, or a wrapped manifest."""
    if isinstance(payload, Mapping):
        if "capabilities" in payload:
            return _iter_manifest_entries(payload["capabilities"])
        if "name" in payload:
            return [(str(payload["name"]), payload)]
        return list(payload.items())

    if isinstance(payload, list):
        entries = []
        for item in payload:
            if isinstance(item, Mapping) and "name" in item:
                entries.append((str(item["name"]), item))
        return entries

    return []


def load_capabilities(root: str | Path | None = None) -> dict[str, Capability]:
    """Convenience wrapper used by the planner and by diagnostics."""
    return CapabilityLoader(root).load_all()
