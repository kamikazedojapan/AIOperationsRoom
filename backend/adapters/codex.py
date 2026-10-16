"""Normalize supported Codex lifecycle hook payloads."""

from __future__ import annotations

from backend.events_contract import EventName, EventSource


CODEX_EVENT_MAP = {
    "SessionStart": EventName.SESSION_STARTED,
    "UserPromptSubmit": EventName.TURN_STARTED,
    "SubagentStart": EventName.AGENT_STARTED,
    "SubagentStop": EventName.AGENT_FINISHED,
    "Stop": EventName.TURN_FINISHED,
    "SessionEnd": EventName.SESSION_FINISHED,
}


def normalize_codex_event(payload: dict) -> dict | None:
    """Translate a prepared Codex hook payload into the internal event contract.

    Codex also emits SessionStart with source=compact, including during an active
    turn. The current internal contract has no compaction fact, so those callbacks
    are intentionally ignored rather than incorrectly resetting the projected
    session state.
    """
    source_event = payload.get("hook_event_name")
    if not source_event:
        raise ValueError("Missing Codex hook_event_name")

    normalized_name = CODEX_EVENT_MAP.get(source_event)
    if normalized_name is None:
        raise ValueError(f"Unsupported Codex event: {source_event}")

    if source_event == "SessionStart" and payload.get("start_source") == "compact":
        return None

    event = {
        "id": payload["id"],
        "evento": normalized_name,
        "source": EventSource.CODEX,
        "source_event": source_event,
        "session_id": payload["session_id"],
        "t": payload["t"],
    }

    for field in ("cwd", "agent_id", "agent_type", "reason"):
        if field in payload:
            event[field] = payload[field]

    return event
