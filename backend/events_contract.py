from enum import StrEnum
from typing import NotRequired, TypedDict

class EventName(StrEnum):
  SESSION_STARTED = "session.started"
  TURN_STARTED = "turn.started"
  AGENT_STARTED = "agent.started"
  AGENT_FINISHED = "agent.finished"
  TURN_FINISHED = "turn.finished"
  SESSION_FINISHED = "session.finished"

class EventSource(StrEnum):
  CLAUDE_CODE = "claude_code"
  CODEX = "codex"
  OPENAI_API = "openai_api"

class NormalizedEvent(TypedDict):
  id: str
  evento: EventName
  source: EventSource
  session_id: str
  t: str

  source_event: NotRequired[str]
  cwd: NotRequired[str]
  agent_id: NotRequired[str]
  agent_type: NotRequired[str]
  reason: NotRequired[str]
  background_tasks: NotRequired[list]

def validate_event(event: dict) -> None:
  required_fields = {
    "id",
    "evento",
    "source",
    "session_id",
    "t",
  }

  missing = required_fields - event.keys()

  if missing:
    raise ValueError(
      f"Missing required event fields: {sorted(missing)}"
    )

  try:
    EventName(event["evento"])
  except ValueError as exc:
    raise ValueError(
      f"Invalid event name: {event['evento']}"
    ) from exc

  try:
    EventSource(event["source"])
  except ValueError as exc:
    raise ValueError(
      f"Invalid event source: {event['source']}"
    ) from exc