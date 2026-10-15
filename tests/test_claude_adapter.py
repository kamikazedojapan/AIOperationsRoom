import pytest

from backend.adapters.claude import normalize_claude_event
from backend.events_contract import EventName, EventSource


def make_payload(**overrides):
  payload = {
    "id": "event-1",
    "hook_event_name": "UserPromptSubmit",
    "session_id": "session-1",
    "t": "2026-10-14T14:00:00Z",
    "cwd": r"C:\projeto",
  }

  payload.update(overrides)
  return payload


def test_normalizes_claude_event():
  event = normalize_claude_event(make_payload())

  assert event["evento"] == EventName.TURN_STARTED
  assert event["source"] == EventSource.CLAUDE_CODE
  assert event["source_event"] == "UserPromptSubmit"
  assert event["session_id"] == "session-1"
  assert event["cwd"] == r"C:\projeto"


def test_maps_all_supperted_claude_events():
  expected = {
    "SessionStart": EventName.SESSION_STARTED,
    "UserPromptSubmit": EventName.TURN_STARTED,
    "SubagentStart": EventName.AGENT_STARTED,
    "SubagentStop": EventName.AGENT_FINISHED,
    "Stop": EventName.TURN_FINISHED,
    "SessionEnd": EventName.SESSION_FINISHED,
  }

  for source_event, normalized_name in expected.items():
    event = normalize_claude_event(
      make_payload(hook_event_name=source_event)
    )

    assert event["evento"] == normalized_name


def test_preserves_optional_fields():
  event = normalize_claude_event(
    make_payload(
      agent_id="agent-1",
      agent_type="worker",
      reason="completed",
      background_tasks=["task-1"],
    )
  )

  assert event["agent_id"] == "agent-1"
  assert event["agent_type"] == "worker"
  assert event["reason"] == "completed"
  assert event["background_tasks"] == ["task-1"]


def test_rejects_missing_hook_event_name():
  payload = make_payload()
  del payload["hook_event_name"]

  with pytest.raises(
    ValueError,
    match="Missing Claude hook_event_name",
  ):
    normalize_claude_event(payload)


def tests_rejects_unsupported_claude_event():
  with pytest.raises(
    ValueError,
    match="Unsupported Claude event",
  ):
    normalize_claude_event(
      make_payload(hook_event_name="UnknownEvent")
    )