import sqlite3

from backend.config import database_path
from backend.db import connect, init_db


def test_init_db_creates_provider_aware_schema(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv(
        "AI_OPERATIONS_ROOM_DATA_DIR",
        str(tmp_path),
    )

    init_db()

    with connect() as con:
        session_columns = {
            row["name"]
            for row in con.execute(
                "PRAGMA table_info(sessao)"
            )
        }

        execution_columns = {
            row["name"]
            for row in con.execute(
                "PRAGMA table_info(execucao)"
            )
        }

        event_columns = {
            row["name"]
            for row in con.execute(
                "PRAGMA table_info(evento)"
            )
        }

    assert {
        "session_key",
        "source",
        "session_id",
    }.issubset(session_columns)

    assert {
        "session_key",
        "source",
        "session_id",
    }.issubset(execution_columns)

    assert {
        "session_key",
        "source",
        "session_id",
    }.issubset(event_columns)


def test_init_db_migrates_legacy_database(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv(
        "AI_OPERATIONS_ROOM_DATA_DIR",
        str(tmp_path),
    )

    raw = sqlite3.connect(
        database_path()
    )

    raw.executescript(
        """
        CREATE TABLE sessao (
            session_id TEXT PRIMARY KEY,
            cwd TEXT NOT NULL,
            ultimo_evento TEXT NOT NULL,
            ultima_atualizacao TEXT NOT NULL
        );

        CREATE TABLE evento (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            nome TEXT NOT NULL,
            ocorrido_em TEXT NOT NULL,
            dados TEXT NOT NULL
        );

        CREATE TABLE execucao (
            chave TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            agent_id TEXT,
            pai_chave TEXT,
            tipo TEXT NOT NULL,
            cwd TEXT NOT NULL,
            estado TEXT NOT NULL,
            origem_encerramento TEXT,
            criado_em TEXT NOT NULL,
            atualizado_em TEXT NOT NULL
        );
        """
    )

    raw.execute(
        """
        INSERT INTO sessao (
            session_id,
            cwd,
            ultimo_evento,
            ultima_atualizacao
        )
        VALUES (?, ?, ?, ?)
        """,
        (
            "legacy-1",
            "/work",
            "session.started",
            "2026-10-16T12:00:00+00:00",
        ),
    )

    raw.execute(
        """
        INSERT INTO evento (
            id,
            session_id,
            nome,
            ocorrido_em,
            dados
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            "event-1",
            "legacy-1",
            "session.started",
            "2026-10-16T12:00:00+00:00",
            "{}",
        ),
    )

    raw.execute(
        """
        INSERT INTO execucao (
            chave,
            session_id,
            agent_id,
            pai_chave,
            tipo,
            cwd,
            estado,
            origem_encerramento,
            criado_em,
            atualizado_em
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "session:legacy-1",
            "legacy-1",
            None,
            None,
            "principal",
            "/work",
            "aguardando",
            None,
            "2026-10-16T12:00:00+00:00",
            "2026-10-16T12:00:00+00:00",
        ),
    )

    raw.commit()
    raw.close()

    init_db()

    with connect() as con:
        session = con.execute(
            "SELECT * FROM sessao"
        ).fetchone()

        event = con.execute(
            "SELECT * FROM evento"
        ).fetchone()

        execution = con.execute(
            "SELECT * FROM execucao"
        ).fetchone()

    assert (
        session["session_key"]
        == "claude_code:legacy-1"
    )

    assert (
        session["source"]
        == "claude_code"
    )

    assert (
        event["session_key"]
        == "claude_code:legacy-1"
    )

    assert (
        execution["chave"]
        == "claude_code:legacy-1:main"
    )


def test_init_db_can_run_twice(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv(
        "AI_OPERATIONS_ROOM_DATA_DIR",
        str(tmp_path),
    )

    init_db()
    init_db()

    with connect() as con:
        columns = {
            row["name"]
            for row in con.execute(
                "PRAGMA table_info(sessao)"
            )
        }

    assert "session_key" in columns
    assert "source" in columns