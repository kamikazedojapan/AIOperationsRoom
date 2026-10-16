"""Small SQLite store for project mappings and session discovery."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Iterator

from backend.config import database_path
from backend.db_migrations import (
    create_provider_schema,
    migrate_provider_identity,
    table_exists,
)


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    con = sqlite3.connect(
        database_path(),
        timeout=15,
        check_same_thread=False,
    )

    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")

    try:
        yield con
        con.commit()

    except Exception:
        con.rollback()
        raise

    finally:
        con.close()


def init_db() -> None:
    with connect() as con:
        con.execute(
            "PRAGMA journal_mode = WAL"
        )

        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS projeto (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT NOT NULL COLLATE NOCASE UNIQUE,
                caminho_local TEXT NOT NULL,
                caminho_key TEXT NOT NULL UNIQUE,
                arquivado INTEGER NOT NULL DEFAULT 0
                    CHECK (arquivado IN (0, 1)),
                criado_em TEXT NOT NULL,
                atualizado_em TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS ingestao (
                chave TEXT PRIMARY KEY,
                valor INTEGER NOT NULL
            );
            """
        )

        if table_exists(
            con,
            "sessao",
        ):
            migrate_provider_identity(con)

        else:
            create_provider_schema(con)