from backend.identity import (
    agent_execution_key,
    main_execution_key,
    session_key,
)

def test_session_key_namespaces_provider():
    assert (
        session_key(
            "claude_code",
            "session-1",
        )
        == "claude_code:session-1"
    )

    assert(
        session_key(
            "codex",
            "session-1",
        )
        == "codex:session-1"
    )

def test_same_native_session_id_does_not_collide():
    claude = session_key(
        "claude_code",
        "same-id",
    )

    codex = session_key(
        "codex",
        "same-id",
    )

    assert claude != codex

def test_main_execution_key_is_namespaced():
    assert (
        agent_execution_key(
            "claude_code",
            "session-1",
            "agent-1",
        )
        == (
            "claude_code:"
            "session-1:"
            "agent:agent-1"
        )
    )

def test_agent_execution_key_is_namespaced():
    assert (
        agent_execution_key(
            "claude_code",
            "session-1",
            "agent-1",
        )
        == (
            "claude_code:"
            "session-1:"
            "agent:agent-1"
        )
    )

def test_same_agente_id_in_different_sessions_does_not_collide():
    first = agent_execution_key(
        "claude-code",
        "session-1",
        "worker",
    )

    second = agent_execution_key(
        "claude_code",
        "session-2",
        "worker",
    )

    assert first != second