from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from backend.config import events_path
from backend.db import connect, init_db
from backend.events import ingest
from backend.events_contract import EventName, EventSource
from backend.reconcile import reconcile


def write_events(*events: dict) -> None:
    with events_path().open("a", encoding="utf-8") as stream:
        for event in events:
            stream.write(json.dumps(event) + "\n")


def test_reconcile_only_applies_claude_liveness(monkeypatch, tmp_path):
    monkeypatch.setenv("AI_OPERATIONS_ROOM_DATA_DIR", str(tmp_path))
    init_db()
    now = datetime.now(timezone.utc)
    old = (now - timedelta(minutes=11)).isoformat(timespec="seconds")

    write_events(
        {
            "id": "claude",
            "evento": EventName.SESSION_STARTED,
            "source": EventSource.CLAUDE_CODE,
            "session_id": "shared",
            "cwd": "/claude",
            "t": old,
        },
        {
            "id": "codex",
            "evento": EventName.SESSION_STARTED,
            "source": EventSource.CODEX,
            "session_id": "shared",
            "cwd": "/codex",
            "t": old,
        },
    )

    with connect() as con:
        assert ingest(con) == 2
        assert reconcile(con, living={"shared": False}, now=now) == 1
        rows = {
            row["session_key"]: dict(row)
            for row in con.execute("SELECT * FROM execucao")
        }

    assert rows["claude_code:shared"]["estado"] == "orfa"
    assert rows["claude_code:shared"]["origem_encerramento"] == "pid_morto"
    assert rows["codex:shared"]["estado"] == "aguardando"
    assert rows["codex:shared"]["origem_encerramento"] is None
