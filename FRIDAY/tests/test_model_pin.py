"""User pin overrides adaptive 3B/7B routing.

Model size is a user preference.  When FRIDAY_LLM_PIN is set the router must
not escalate on query complexity, because escalation can start a slower
backend (e.g. a CPU-only 7B) and blow the conversation response timeout.
"""

import pytest

from core.router.adaptive_router import AdaptiveRouter

COMPLEX_UTTERANCE = (
    "analyze deeply and build a comprehensive multi-step website with research"
)


@pytest.mark.asyncio
async def test_pin_3b_overrides_complex_escalation(monkeypatch):
    monkeypatch.setenv("FRIDAY_LLM_PIN", "3b")
    router = AdaptiveRouter()

    model, reason = await router.decide_model(COMPLEX_UTTERANCE)

    assert model == "3b"
    assert reason == "pinned_by_user"


@pytest.mark.asyncio
async def test_pin_7b_is_honoured(monkeypatch):
    monkeypatch.setenv("FRIDAY_LLM_PIN", "7b")
    router = AdaptiveRouter()

    model, reason = await router.decide_model("what time is it")

    assert model == "7b"
    assert reason == "pinned_by_user"


@pytest.mark.asyncio
async def test_pin_is_ignored_when_absent_or_invalid(monkeypatch):
    monkeypatch.delenv("FRIDAY_LLM_PIN", raising=False)
    assert AdaptiveRouter()._pinned_model() is None

    monkeypatch.setenv("FRIDAY_LLM_PIN", "300b")
    assert AdaptiveRouter()._pinned_model() is None

    model, reason = await AdaptiveRouter().decide_model("what time is it")
    assert model == "3b"
    assert reason != "pinned_by_user"


@pytest.mark.asyncio
async def test_pinned_route_does_not_switch_models(monkeypatch):
    """A pin must leave the manager untouched once it already serves that model."""
    from unittest.mock import AsyncMock, MagicMock

    monkeypatch.setenv("FRIDAY_LLM_PIN", "3b")
    manager = MagicMock()
    manager.current_model = "3b"
    manager.switch_model = AsyncMock()

    router = AdaptiveRouter(model_manager=manager)
    model, _ = await router.route(COMPLEX_UTTERANCE)

    assert model == "3b"
    manager.switch_model.assert_not_awaited()
