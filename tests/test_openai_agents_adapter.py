from backend.adapters.openai_agents import normalize_openai_agent_event
from backend.events_contract import EventName, EventSource


def test_session_created_is_normalized():
    event = normalize_openai_agent_event({
        "type": "agent.session.created",
        "event_id": "evt-1",
        "session": {"id": "sess-1"},
    })

    assert event is not None
    assert event["evento"] == EventName.SESSION_STARTED
    assert event["source"] == EventSource.OPENAI_API
    assert event["source_event"] == "agent.session.created"
    assert event["session_id"] == "sess-1"


def test_turn_lifecycle_is_normalized():
    started = normalize_openai_agent_event({
        "type": "agent.session.turn.in_progress",
        "event_id": "evt-2",
        "session_id": "sess-1",
        "turn": {"id": "turn-1"},
    })
    finished = normalize_openai_agent_event({
        "type": "agent.session.turn.completed",
        "event_id": "evt-3",
        "session_id": "sess-1",
        "turn": {"id": "turn-1"},
    })

    assert started["evento"] == EventName.TURN_STARTED
    assert finished["evento"] == EventName.TURN_FINISHED


def test_subagent_lifecycle_is_normalized():
    started = normalize_openai_agent_event({
        "type": "agent.session.subagent.created",
        "event_id": "evt-4",
        "session_id": "sess-1",
        "subagent": {"id": "agent-1", "name": "reviewer"},
    })
    finished = normalize_openai_agent_event({
        "type": "agent.session.subagent.closed",
        "event_id": "evt-5",
        "session_id": "sess-1",
        "subagent": {"id": "agent-1", "name": "reviewer"},
    })

    assert started["evento"] == EventName.AGENT_STARTED
    assert started["agent_id"] == "agent-1"
    assert started["agent_type"] == "reviewer"
    assert finished["evento"] == EventName.AGENT_FINISHED


def test_content_events_are_not_global_telemetry():
    assert normalize_openai_agent_event({
        "type": "agent.session.turn.output_text.delta",
        "event_id": "evt-text",
        "session_id": "sess-1",
        "delta": "secret text",
    }) is None


def test_missing_type_is_rejected():
    try:
        normalize_openai_agent_event({"session_id": "sess-1"})
    except ValueError as exc:
        assert "event type" in str(exc)
    else:
        raise AssertionError("expected ValueError")
