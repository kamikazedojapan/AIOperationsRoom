import json

from backend.config import events_path
from backend.db import connect, init_db
from backend.events import ingest
from backend.events_contract import (
    EventName,
    EventSource,
)


def write_events(*events: dict) -> None:
    events_path().write_text(
        "".join(
            json.dumps(event)
            + "\n"
            for event in events
        ),
        encoding="utf-8",
    )


def test_same_session_id_across_providers_does_not_collide(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv(
        "AI_OPERATIONS_ROOM_DATA_DIR",
        str(tmp_path),
    )

    init_db()

    write_events(
        {
            "id": "claude-event",
            "evento": EventName.SESSION_STARTED,
            "source": EventSource.CLAUDE_CODE,
            "session_id": "shared",
            "cwd": "/claude",
            "t": "2026-10-16T12:00:00+00:00",
        },
        {
            "id": "codex-event",
            "evento": EventName.SESSION_STARTED,
            "source": EventSource.CODEX,
            "session_id": "shared",
            "cwd": "/codex",
            "t": "2026-10-16T12:01:00+00:00",
        },
    )

    with connect() as con:
        assert ingest(con) == 2

        sessions = {
            row["session_key"]
            for row in con.execute(
                "SELECT session_key FROM sessao"
            )
        }

        executions = {
            row["chave"]
            for row in con.execute(
                "SELECT chave FROM execucao"
            )
        }

        sources = {
            row["source"]
            for row in con.execute(
                "SELECT source FROM evento"
            )
        }

    assert sessions == {
        "claude_code:shared",
        "codex:shared",
    }

    assert executions == {
        "claude_code:shared:main",
        "codex:shared:main",
    }

    assert sources == {
        "claude_code",
        "codex",
    }


def test_same_agent_id_in_different_sessions_does_not_collide(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv(
        "AI_OPERATIONS_ROOM_DATA_DIR",
        str(tmp_path),
    )

    init_db()

    write_events(
        {
            "id": "event-1",
            "evento": EventName.AGENT_STARTED,
            "source": EventSource.CLAUDE_CODE,
            "session_id": "session-1",
            "agent_id": "worker",
            "cwd": "/one",
            "t": "2026-10-16T12:00:00+00:00",
        },
        {
            "id": "event-2",
            "evento": EventName.AGENT_STARTED,
            "source": EventSource.CLAUDE_CODE,
            "session_id": "session-2",
            "agent_id": "worker",
            "cwd": "/two",
            "t": "2026-10-16T12:01:00+00:00",
        },
    )

    with connect() as con:
        assert ingest(con) == 2

        agents = {
            row["chave"]
            for row in con.execute(
                """
                SELECT chave
                FROM execucao
                WHERE agent_id = 'worker'
                """
            )
        }

    assert agents == {
        "claude_code:session-1:agent:worker",
        "claude_code:session-2:agent:worker",
    }