"""n8n automation tool integration for FRIDAY.

Provides declarative workflow creation and inspection against local or remote n8n.
"""

from __future__ import annotations

import json
import os
from typing import Any

import httpx

from ..security.credentials import get_secret
from .tool_models import ToolResult


class N8nTools:
    """Manages n8n workflow creation and listing via n8n REST API."""

    def __init__(self, base_url: str = "http://127.0.0.1:5678") -> None:
        self.base_url = os.getenv("N8N_BASE_URL", base_url).rstrip("/")

    def _get_api_key(self) -> str | None:
        return get_secret("N8N_API_KEY")

    async def create_workflow(
        self,
        name: str,
        workflow_json: str | dict[str, Any] = "",
        **kwargs: Any,
    ) -> ToolResult:
        """Create a new workflow in n8n and return its workflow ID."""
        api_key = self._get_api_key()
        if not api_key:
            return ToolResult(
                False,
                "",
                "n8n API key missing: set N8N_API_KEY in .env or environment",
                metadata={"status_code": 401},
            )

        headers = {"X-N8N-API-KEY": api_key, "Content-Type": "application/json"}
        if isinstance(workflow_json, str) and workflow_json.strip():
            try:
                payload = json.loads(workflow_json)
            except json.JSONDecodeError:
                payload = {"name": name, "nodes": [], "connections": {}}
        elif isinstance(workflow_json, dict):
            payload = dict(workflow_json)
        else:
            payload = {"name": name, "nodes": [], "connections": {}}

        payload.setdefault("name", name)
        payload.setdefault("nodes", [])
        payload.setdefault("connections", {})
        # The public n8n API (v2.x) rejects a create without `settings`:
        # HTTP 400 "request/body must have required property 'settings'".
        payload.setdefault("settings", {})

        # An empty workflow is not an automation. Creating one and reporting
        # success answered "build me a workflow" with a hollow shell, so refuse
        # before the call instead of verifying a meaningless 200.
        nodes = payload.get("nodes")
        if not isinstance(nodes, list) or not nodes:
            return ToolResult(
                False,
                "",
                "n8n workflow needs at least one node: pass workflow_json with "
                "nodes and connections (trigger + actions)",
                metadata={"status_code": None, "reason": "empty_workflow"},
            )

        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                resp = await client.post(
                    f"{self.base_url}/api/v1/workflows",
                    json=payload,
                    headers=headers,
                )
                if resp.status_code in (200, 201):
                    data = resp.json()
                    wf_id = str(data.get("id", "unknown"))
                    return ToolResult(
                        True,
                        f"Workflow '{name}' created with id: {wf_id}",
                        # Report the real status: n8n answers 201 Created, and a
                        # verifier must judge what actually came back.
                        metadata={
                            "status_code": resp.status_code,
                            "workflow_id": wf_id,
                            "data": data,
                        },
                    )
                return ToolResult(
                    False,
                    "",
                    f"n8n API error: HTTP {resp.status_code} - {resp.text[:200]}",
                    metadata={"status_code": resp.status_code},
                )
            except Exception as e:
                return ToolResult(
                    False,
                    "",
                    # Name the exception type: some httpx failures stringify
                    # to an empty message, which hid the real cause before.
                    f"Failed to connect to n8n at {self.base_url}: {type(e).__name__}: {e!r}",
                    metadata={"status_code": 500},
                )

    async def list_workflows(self, **kwargs: Any) -> ToolResult:
        """List active and saved workflows in n8n."""
        api_key = self._get_api_key()
        if not api_key:
            return ToolResult(
                False,
                "",
                "n8n API key missing: set N8N_API_KEY in .env or environment",
                metadata={"status_code": 401},
            )

        headers = {"X-N8N-API-KEY": api_key}
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                resp = await client.get(
                    f"{self.base_url}/api/v1/workflows",
                    headers=headers,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    workflows = data.get("data", [])
                    summary = [
                        f"- {wf.get('name')} (id: {wf.get('id')}, active: {wf.get('active')})"
                        for wf in workflows
                    ]
                    return ToolResult(
                        True,
                        "\n".join(summary) if summary else "No workflows found.",
                        metadata={"status_code": 200, "count": len(workflows)},
                    )
                return ToolResult(
                    False,
                    "",
                    f"n8n API error: HTTP {resp.status_code}",
                    metadata={"status_code": resp.status_code},
                )
            except Exception as e:
                return ToolResult(
                    False,
                    "",
                    # Name the exception type: some httpx failures stringify
                    # to an empty message, which hid the real cause before.
                    f"Failed to connect to n8n at {self.base_url}: {type(e).__name__}: {e!r}",
                    metadata={"status_code": 500},
                )
