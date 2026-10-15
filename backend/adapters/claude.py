from backend.events_contract import EventName, EventSource

CLAUDE_EVENT_MAP = {
  "SessionStart": EventName.SESSION_STARTED,
  "UserPromptSubmit": EventName.TURN_STARTED,
  "SubagentStart": EventName.AGENT_STARTED,
  "SubagentStop": EventName.AGENT_FINISHED,
  "Stop": EventName.TURN_FINISHED,
  "SessionEnd": EventName.SESSION_FINISHED,
}


def normalize_claude_event(payload: dict) -> dict:
  source_event = payload.get("hook_event_name")

  if not source_event:
    raise ValueError("Missing Claude hook_event_name")

  normalized_name = CLAUDE_EVENT_MAP.get(source_event)

  if normalized_name is None:
    raise ValueError(
      f"Unsupported Claude event: {source_event}"
    )

  event = {
    "id": payload["id"],
    "evento": normalized_name,
    "source": EventSource.CLAUDE_CODE,
    "source_event": source_event,
    "session_id": payload["session_id"],
    "t": payload["t"],
  }

  optional_fields = (
    "cwd",
    "agent_id",
    "agent_type",
    "reason",
    "background_tasks",
  )

  for field in optional_fields:
    if field in payload:
      event[field] = payload[field]

  return event