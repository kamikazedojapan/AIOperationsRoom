from __future__ import annotations

import sqlite3

from backend.events_contract import EventSource


LEGACY_SOURCE = EventSource.CLAUDE_CODE.value


def table_exists(
    con: sqlite3.Connection,
    table: str,
) -> bool:
    row = con.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table'
          AND name = ?
        """,
        (table,),
    ).fetchone()

    return row is not None


def column_names(
    con: sqlite3.Connection,
    table: str,
) -> set[str]:
    rows = con.execute(
        f"PRAGMA table_info({table})"
    ).fetchall()

    return {
        row[1]
        for row in rows
    }


def create_provider_schema(
    con: sqlite3.Connection,
) -> None:
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS sessao (
            session_key TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            session_id TEXT NOT NULL,
            cwd TEXT NOT NULL,
            ultimo_evento TEXT NOT NULL,
            ultima_atualizacao TEXT NOT NULL,
            UNIQUE(source, session_id)
        );

        CREATE TABLE IF NOT EXISTS evento (
            id TEXT PRIMARY KEY,
            session_key TEXT NOT NULL,
            source TEXT NOT NULL,
            session_id TEXT NOT NULL,
            nome TEXT NOT NULL,
            ocorrido_em TEXT NOT NULL,
            dados TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS execucao (
            chave TEXT PRIMARY KEY,
            session_key TEXT NOT NULL,
            source TEXT NOT NULL,
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

        CREATE INDEX IF NOT EXISTS idx_execucao_session_key
            ON execucao(session_key);

        CREATE INDEX IF NOT EXISTS idx_evento_session_key
            ON evento(session_key);

        CREATE INDEX IF NOT EXISTS idx_execucao_source_session
            ON execucao(source, session_id);

        CREATE INDEX IF NOT EXISTS idx_evento_source_session
            ON evento(source, session_id);
        """
    )


def migrate_provider_identity(
    con: sqlite3.Connection,
) -> bool:
    if not table_exists(
        con,
        "sessao",
    ):
        return False

    if "session_key" in column_names(
        con,
        "sessao",
    ):
        create_provider_schema(con)
        return False

    con.execute(
        "DROP INDEX IF EXISTS idx_execucao_session"
    )

    con.execute(
        "DROP INDEX IF EXISTS idx_evento_session"
    )

    con.execute(
        "ALTER TABLE sessao "
        "RENAME TO sessao_legacy"
    )

    con.execute(
        "ALTER TABLE evento "
        "RENAME TO evento_legacy"
    )

    con.execute(
        "ALTER TABLE execucao "
        "RENAME TO execucao_legacy"
    )

    create_provider_schema(con)

    con.execute(
        """
        INSERT INTO sessao (
            session_key,
            source,
            session_id,
            cwd,
            ultimo_evento,
            ultima_atualizacao
        )
        SELECT
            ? || ':' || session_id,
            ?,
            session_id,
            cwd,
            ultimo_evento,
            ultima_atualizacao
        FROM sessao_legacy
        """,
        (
            LEGACY_SOURCE,
            LEGACY_SOURCE,
        ),
    )

    con.execute(
        """
        INSERT INTO evento (
            id,
            session_key,
            source,
            session_id,
            nome,
            ocorrido_em,
            dados
        )
        SELECT
            id,
            ? || ':' || session_id,
            ?,
            session_id,
            nome,
            ocorrido_em,
            dados
        FROM evento_legacy
        """,
        (
            LEGACY_SOURCE,
            LEGACY_SOURCE,
        ),
    )

    con.execute(
        """
        INSERT INTO execucao (
            chave,
            session_key,
            source,
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
        SELECT
            CASE
                WHEN agent_id IS NULL
                     OR agent_id = ''
                THEN
                    ? || ':' ||
                    session_id ||
                    ':main'
                ELSE
                    ? || ':' ||
                    session_id ||
                    ':agent:' ||
                    agent_id
            END,
            ? || ':' || session_id,
            ?,
            session_id,
            agent_id,
            CASE
                WHEN pai_chave IS NULL
                THEN NULL
                ELSE
                    ? || ':' ||
                    session_id ||
                    ':main'
            END,
            tipo,
            cwd,
            estado,
            origem_encerramento,
            criado_em,
            atualizado_em
        FROM execucao_legacy
        """,
        (
            LEGACY_SOURCE,
            LEGACY_SOURCE,
            LEGACY_SOURCE,
            LEGACY_SOURCE,
            LEGACY_SOURCE,
        ),
    )

    con.executescript(
        """
        DROP TABLE sessao_legacy;
        DROP TABLE evento_legacy;
        DROP TABLE execucao_legacy;
        """
    )

    return True