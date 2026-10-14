import pytest

from backend.events_contract import (
  EventName,
  EventSource,
  validate_event,
)

def make_event(**overrides):
  event = {
    "id": "event-1",
    "evento": EventName.TURN_STARTED,
    "source": EventSource.CLAUDE_CODE,
    "session_id": "session-1",
    "t": "2026-10-14T13:00:00Z",
  }

  event.update(overrides)
  return event


def test_valid_event():
  event = make_event()

  validate_event(event)


def test_missing_required_field():
  event = make_event()
  del event["session_id"]

  with pytest.raises(
    ValueError,
    match="Missing required event fields",
  ):
    validate_event(event)

def test_invalid_event_name():
  event = make_event(evento="session.working")

  with pytest.raises(
    ValueError,
    match="Invalid event name"
  ):
    validate_event(event)

def test_invalid_event_source():
  event = make_event(source="unknown_provider")

  with pytest.raises(
    ValueError,
    match="Invalid event source",
  ):
    validate_event(event)

def test_optional_fields_are_not_required():
  event = make_event()

  assert "cwd" not in event
  assert "agent_id" not in event

  validate_event(event)