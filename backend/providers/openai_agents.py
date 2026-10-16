"""OpenAI Agents API TaskProvider for the Agent Console."""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone

from backend.adapters.openai_agents import normalize_openai_agent_event
from backend.config import events_path
from backend.events_contract import EventName, EventSource
from backend.task_runner import ProviderResult, TaskCancelled


AGENT_INSTRUCTIONS = {
    "general": "Complete the user's task carefully. Report the concrete result and important limitations.",
    "coder": "Act as a software engineering agent. Inspect, implement, verify, and report concrete results.",
    "reviewer": "Act as a rigorous reviewer. Find correctness, security, maintainability, and testing issues, then summarize actionable findings.",
}

FAILURE_EVENTS = {
    "error",
    "agent.session.failed",
    "agent.session.environment.failed",
    "agent.session.turn.failed",
}
CANCELLED_EVENTS = {"agent.session.turn.cancelled"}


def _openai_class():
    try:
        from openai import OpenAI
    except ImportError:
        return None
    return OpenAI


def _event_dict(event) -> dict:
    if isinstance(event, dict):
        return event
    for name in ("to_dict", "model_dump"):
        method = getattr(event, name, None)
        if callable(method):
            value = method()
            if isinstance(value, dict):
                return value
    method = getattr(event, "to_json", None)
    if callable(method):
        value = method(indent=None)
        if isinstance(value, str):
            decoded = json.loads(value)
            if isinstance(decoded, dict):
                return decoded
    raise TypeError(f"Unsupported OpenAI event object: {type(event).__name__}")


def _session_id(payload: dict) -> str | None:
    direct = payload.get("session_id")
    if isinstance(direct, str) and direct:
        return direct
    session = payload.get("session")
    if isinstance(session, dict):
        value = session.get("id") or session.get("session_id")
        if isinstance(value, str) and value:
            return value
    return None


def _append_global_event(event: dict) -> None:
    path = events_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(event, ensure_ascii=False) + "\n")


def _record_deleted_session(session_id: str, emit) -> None:
    """Record a successful local DELETE call as a normalized session finish.

    The Agents API does not emit a deletion webhook/stream event. This is therefore
    an observation made by the Operations Room client after the DELETE succeeds,
    not a provider-emitted lifecycle event.
    """
    event = {
        "id": f"openai:delete:{session_id}:{uuid.uuid4()}",
        "evento": EventName.SESSION_FINISHED,
        "source": EventSource.OPENAI_API,
        "source_event": "client.session.delete",
        "session_id": session_id,
        "t": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "reason": "deleted",
    }
    _append_global_event(event)
    emit(
        "provider.lifecycle",
        source_event="client.session.delete",
        data={"event": event["evento"], "provider_session_id": session_id},
    )


class OpenAIAgentsProvider:
    source = "openai_api"

    def available(self) -> bool:
        return bool(os.environ.get("OPENAI_API_KEY")) and _openai_class() is not None

    def unavailable_reason(self) -> str | None:
        if not os.environ.get("OPENAI_API_KEY"):
            return "OPENAI_API_KEY is not configured."
        if _openai_class() is None:
            return "The OpenAI Python SDK is not installed."
        return None

    def run(self, task: dict, emit, is_cancelled) -> ProviderResult:
        OpenAI = _openai_class()
        if OpenAI is None:
            raise RuntimeError("The OpenAI Python SDK is not installed.")

        model = os.environ.get("AI_OPERATIONS_ROOM_OPENAI_MODEL", "gpt-6-astra")
        instructions = AGENT_INSTRUCTIONS.get(task["agent"], AGENT_INSTRUCTIONS["general"])
        provider_session_id: str | None = None
        output_parts: list[str] = []
        cancel_sent = False

        with OpenAI() as client:
            try:
                create = client.beta.agents.sessions.create(
                    agent={
                        "model": model,
                        "instructions": instructions,
                        "multi_agent": {"enabled": True, "max_concurrent_subagents": 4},
                    },
                    environment={"type": "openai_hosted"},
                    input=task["prompt"],
                    stream=True,
                )
                with create.with_result_collection() as stream:
                    for raw_event in stream:
                        payload = _event_dict(raw_event)
                        source_event = payload.get("type")
                        sid = _session_id(payload)
                        if sid and sid != provider_session_id:
                            provider_session_id = sid
                            emit(
                                "provider.session",
                                source_event=source_event,
                                data={"provider_session_id": sid},
                            )

                        normalized = normalize_openai_agent_event(payload)
                        if normalized is not None:
                            _append_global_event(normalized)
                            emit(
                                "provider.lifecycle",
                                source_event=source_event,
                                data={
                                    "event": normalized["evento"],
                                    "agent_id": normalized.get("agent_id"),
                                },
                            )

                        if source_event == "agent.session.turn.output_text.delta":
                            delta = payload.get("delta")
                            if isinstance(delta, str) and delta:
                                output_parts.append(delta)
                                emit("output.delta", source_event=source_event, message=delta)

                        if source_event in FAILURE_EVENTS:
                            error = payload.get("error")
                            if isinstance(error, dict):
                                error = error.get("message")
                            raise RuntimeError(str(error or f"OpenAI Agents event failed: {source_event}"))

                        if source_event in CANCELLED_EVENTS:
                            raise TaskCancelled("OpenAI Agents turn was cancelled.")

                        if is_cancelled() and provider_session_id and not cancel_sent:
                            client.beta.agents.sessions.events.create(
                                provider_session_id,
                                events=[{"type": "agent.session.input.cancel"}],
                            )
                            cancel_sent = True
                            emit(
                                "provider.cancel_sent",
                                data={"provider_session_id": provider_session_id},
                            )

                    result = stream.get_final_result()

                final_session_id = getattr(result, "session_id", None)
                if isinstance(final_session_id, str) and final_session_id:
                    provider_session_id = final_session_id
                final_output = getattr(result, "output_text", None)
                if isinstance(final_output, str) and final_output:
                    output = final_output
                else:
                    output = "".join(output_parts)
                return ProviderResult(output=output, provider_session_id=provider_session_id)
            finally:
                if (
                    provider_session_id
                    and os.environ.get("AI_OPERATIONS_ROOM_KEEP_OPENAI_SESSIONS") != "1"
                ):
                    try:
                        client.beta.agents.sessions.delete(provider_session_id)
                    except Exception as exc:
                        emit(
                            "provider.cleanup.failed",
                            message=str(exc),
                            data={"provider_session_id": provider_session_id},
                        )
                    else:
                        _record_deleted_session(provider_session_id, emit)
