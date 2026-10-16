"""Normalize supported OpenAI Agents API lifecycle events."""

from __future__ import annotations

from datetime import datetime, timezone

from backend.events_contract import EventName, EventSource


OPENAI_AGENT_EVENT_MAP = {
    "agent.session.created": EventName.SESSION_STARTED,
    "agent.session.turn.in_progress": EventName.TURN_STARTED,
    "agent.session.subagent.created": EventName.AGENT_STARTED,
    "agent.session.subagent.active": EventName.AGENT_STARTED,
    "agent.session.subagent.closed": EventName.AGENT_FINISHED,
    "agent.session.turn.completed": EventName.TURN_FINISHED,
    "agent.session.deleted": EventName.SESSION_FINISHED,
}


def _session_id(payload: dict) -> str | None:
    direct = payload.get("session_id")
    if isinstance(direct, str) and direct:
        return direct

    session = payload.get("session")
    if isinstance(session, dict):
        value = session.get("id") or session.get("session_id")
        if isinstance(value, str) and value:
            return value

    subagent = payload.get("subagent")
    if isinstance(subagent, dict):
        value = subagent.get("session_id")
        if isinstance(value, str) and value:
            return value

    return None


def normalize_openai_agent_event(payload: dict) -> dict | None:
    """Translate observable Agents API lifecycle facts into the internal contract.

    Content streaming events are intentionally ignored here. The global Operations
    Room remains metadata-only; text submitted through Agent Console belongs to the
    task record, not to the telemetry event stream.
    """
    source_event = payload.get("type")
    if not isinstance(source_event, str) or not source_event:
        raise ValueError("Missing OpenAI Agents event type")

    normalized_name = OPENAI_AGENT_EVENT_MAP.get(source_event)
    if normalized_name is None:
        return None

    session_id = _session_id(payload)
    if not session_id:
        raise ValueError(f"Missing session id for OpenAI Agents event: {source_event}")

    event_id = payload.get("event_id")
    if not isinstance(event_id, str) or not event_id:
        event_id = f"openai:{source_event}:{session_id}:{payload.get('sequence_number', '')}"

    event = {
        "id": event_id,
        "evento": normalized_name,
        "source": EventSource.OPENAI_API,
        "source_event": source_event,
        "session_id": session_id,
        "t": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }

    subagent = payload.get("subagent")
    if isinstance(subagent, dict):
        agent_id = subagent.get("id")
        if isinstance(agent_id, str) and agent_id:
            event["agent_id"] = agent_id
        agent_type = subagent.get("name") or subagent.get("type")
        if isinstance(agent_type, str) and agent_type:
            event["agent_type"] = agent_type

    if source_event == "agent.session.deleted":
        event["reason"] = "deleted"

    return event
