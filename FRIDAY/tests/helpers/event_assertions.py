from core.events.models import Event
from core.events.event_types import EventType


def assert_user_speech_event(event: Event, status: str | None = None, text: str | None = None) -> None:
    assert event.event_type == EventType.USER_SPEECH
    if status is not None:
        assert event.payload.get("status") == status
    if text is not None:
        assert event.payload.get("text") == text


def assert_state_updated_event(event: Event, turn: str | None = None, owner: str | None = None) -> None:
    assert event.event_type == EventType.STATE_UPDATED
    if turn is not None:
        assert event.payload.get("turn") == turn
    if owner is not None:
        assert event.payload.get("owner") == owner


def assert_error_event(event: Event, component: str | None = None, error_contains: str | None = None) -> None:
    assert event.event_type == EventType.ERROR
    if component is not None:
        assert event.payload.get("component") == component
    if error_contains is not None:
        assert error_contains in event.payload.get("error", "")
