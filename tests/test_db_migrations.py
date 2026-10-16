import sqlite3

from backend.db_migrations import (
    migrate_provider_identity,
)


def legacy_database() -> sqlite3.Connection:
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row

    con.executescript(
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

        CREATE INDEX idx_execucao_session
            ON execucao(session_id);

        CREATE INDEX idx_evento_session
            ON evento(session_id);
        """
    )

    return con


def test_migrates_legacy_provider_identity():
    con = legacy_database()

    con.execute(
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
            "session-1",
            "/work",
            "session.started",
            "2026-10-16T10:00:00+00:00",
        ),
    )

    con.execute(
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
            "session-1",
            "session.started",
            "2026-10-16T10:00:00+00:00",
            "{}",
        ),
    )

    con.execute(
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
            "session:session-1",
            "session-1",
            None,
            None,
            "principal",
            "/work",
            "aguardando",
            None,
            "2026-10-16T10:00:00+00:00",
            "2026-10-16T10:00:00+00:00",
        ),
    )

    con.execute(
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
            "agent:worker",
            "session-1",
            "worker",
            "session:session-1",
            "subagente",
            "/work",
            "trabalhando",
            None,
            "2026-10-16T10:01:00+00:00",
            "2026-10-16T10:01:00+00:00",
        ),
    )

    migrated = migrate_provider_identity(con)

    assert migrated is True

    session = con.execute(
        "SELECT * FROM sessao"
    ).fetchone()

    assert (
        session["session_key"]
        == "claude_code:session-1"
    )

    assert session["source"] == "claude_code"
    assert session["session_id"] == "session-1"

    executions = con.execute(
        """
        SELECT *
        FROM execucao
        ORDER BY agent_id
        """
    ).fetchall()

    main = executions[0]
    agent = executions[1]

    assert (
        main["chave"]
        == "claude_code:session-1:main"
    )

    assert (
        agent["chave"]
        == (
            "claude_code:"
            "session-1:"
            "agent:worker"
        )
    )

    assert (
        agent["pai_chave"]
        == "claude_code:session-1:main"
    )

    event = con.execute(
        "SELECT * FROM evento"
    ).fetchone()

    assert (
        event["session_key"]
        == "claude_code:session-1"
    )

    assert event["source"] == "claude_code"

    con.close()


def test_migration_is_idempotent():
    con = legacy_database()

    assert (
        migrate_provider_identity(con)
        is True
    )

    assert (
        migrate_provider_identity(con)
        is False
    )

    con.close()