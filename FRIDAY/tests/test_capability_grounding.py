"""Grounding: a private-data request no capability serves must be refused."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

import pytest

from core.logging.logger import get_logger
from core.orchestrator.workflow_trigger import WorkflowTriggerMixin
from core.tools.capability import Capability, CapabilityError
from core.tools.capability_loader import CapabilityLoader
from core.tools.grounding import (
    covered_domains,
    grounding_refusal,
    requested_domains,
    uncovered_domain,
)

FRIDAY_ROOT = Path(__file__).resolve().parents[1]
CAPABILITIES_DIR = FRIDAY_ROOT / "capabilities"


def _caps() -> dict[str, Capability]:
    return CapabilityLoader(CAPABILITIES_DIR).load_all()


def test_an_email_request_is_detected():
    assert requested_domains("find something good on my email") == ["email"]


def test_conceptual_email_questions_are_not_data_requests():
    assert requested_domains("what is email") == []
    assert requested_domains("explain how email works") == []


def test_shipped_manifests_declare_no_private_domain():
    covered = covered_domains(_caps())
    assert "email" not in covered
    assert "calendar" not in covered
    assert "messages" not in covered
    # ...but they do declare what they legitimately reach.
    assert "public_web" in covered
    assert "workspace_files" in covered


def test_email_request_is_uncovered_by_the_real_capabilities():
    assert uncovered_domain("find something good on my email", _caps()) == "email"


def test_declaring_email_coverage_removes_the_gap():
    capabilities = dict(_caps())
    capabilities["email_search"] = Capability.from_dict(
        {
            "name": "email_search",
            "description": "search the user's own inbox",
            "risk": "RESTRICTED",
            "covers": ["email"],
        }
    )
    assert uncovered_domain("find something good on my email", capabilities) is None


def test_calendar_and_messages_are_grounded_too():
    capabilities = _caps()
    assert uncovered_domain("check my calendar for tomorrow", capabilities) == "calendar"
    assert uncovered_domain("any new whatsapp messages", capabilities) == "messages"


def test_a_normal_request_has_no_gap():
    assert uncovered_domain("what is the capital of france", _caps()) is None
    assert uncovered_domain("make a food website plan", _caps()) is None


def test_unknown_coverage_token_is_rejected():
    with pytest.raises(CapabilityError, match="unknown coverage"):
        Capability.from_dict(
            {"name": "bad_covers", "description": "x", "covers": ["everything"]}
        )


def test_refusal_names_the_domain_and_admits_the_limit():
    message = grounding_refusal("email")
    assert "email" in message
    assert "not going to guess" in message


# --- end-to-end through the turn hook ---------------------------------------
class _StubBus:
    _running = True

    def __init__(self) -> None:
        self.events: list[Any] = []

    async def publish(self, event: Any) -> None:
        self.events.append(event)

    def subscribe(self, *args: Any, **kwargs: Any) -> None:
        return None


class _StubConversation(WorkflowTriggerMixin):
    name = "conversation"

    def __init__(self, bus: _StubBus) -> None:
        self.event_bus = bus
        self.logger = get_logger("tests.grounding")
        self.prompt_planner = None
        self._pending_workflow_correlations: set[str] = set()


def test_a_private_data_turn_ends_with_an_honest_refusal():
    bus = _StubBus()
    stub = _StubConversation(bus)

    handled = asyncio.run(
        stub._try_refuse_uncovered_capability(
            "find something good on my email", "turn-1", "corr-1", time.perf_counter()
        )
    )

    assert handled is True
    texts = [str(event.payload.get("text", "")) for event in bus.events]
    assert any("email" in text and "not going to guess" in text for text in texts)
    # The turn must close, or the assistant waits forever for a response.
    assert len(bus.events) == 2


def test_an_ordinary_turn_is_not_intercepted():
    bus = _StubBus()
    stub = _StubConversation(bus)

    handled = asyncio.run(
        stub._try_refuse_uncovered_capability(
            "what is the capital of france", "turn-2", "corr-2", time.perf_counter()
        )
    )

    assert handled is False
    assert bus.events == []
