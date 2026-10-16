from __future__ import annotations

import pytest

from backend.adapters.codex import CODEX_EVENT_MAP, normalize_codex_event
from backend.events_contract import EventName, EventSource


def make_payload(native: str, **extra) -> dict:
    return {
        "id": f"id-{native}",
        "hook_event_name": native,
        "session_id": "session-1",
        "t": "2026-10-16T19:00:00+00:00",
        **extra,
    }


def test_maps_all_supported_codex_lifecycle_events():
    expected = {
        "SessionStart": EventName.SESSION_STARTED,
        "UserPromptSubmit": EventName.TURN_STARTED,
        "SubagentStart": EventName.AGENT_STARTED,
        "SubagentStop": EventName.AGENT_FINISHED,
        "Stop": EventName.TURN_FINISHED,
        "SessionEnd": EventName.SESSION_FINISHED,
    }
    assert CODEX_EVENT_MAP == expected

    for native, normalized in expected.items():
        event = normalize_codex_event(make_payload(native))
        assert event is not None
        assert event["evento"] == normalized
        assert event["source"] == EventSource.CODEX
        assert event["source_event"] == native


def test_preserves_supported_agent_metadata():
    event = normalize_codex_event(
        make_payload(
            "SubagentStart",
            cwd="/work",
            agent_id="worker-1",
            agent_type="reviewer",
        )
    )
    assert event is not None
    assert event["cwd"] == "/work"
    assert event["agent_id"] == "worker-1"
    assert event["agent_type"] == "reviewer"


def test_compaction_session_start_is_ignored():
    assert normalize_codex_event(
        make_payload("SessionStart", start_source="compact")
    ) is None


def test_rejects_unsupported_or_missing_event():
    with pytest.raises(ValueError, match="Unsupported Codex event"):
        normalize_codex_event(make_payload("PreToolUse"))

    payload = make_payload("Stop")
    payload.pop("hook_event_name")
    with pytest.raises(ValueError, match="Missing Codex hook_event_name"):
        normalize_codex_event(payload)
