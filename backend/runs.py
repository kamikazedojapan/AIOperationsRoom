"""Projection of normalized events into provider-aware run states."""

from __future__ import annotations

import json
import sqlite3

from backend.events_contract import EventName
from backend.identity import (
    agent_execution_key,
    main_execution_key,
    session_key,
)


ACTIVE = {
    "trabalhando",
    "delegando",
    "aguardando",
}


def key_for(event: dict) -> str:
    source = event["source"]
    session_id = event["session_id"]

    agent_id = event.get("agent_id")

    if isinstance(agent_id, str) and agent_id:
        return agent_execution_key(
            source,
            session_id,
            agent_id,
        )

    return main_execution_key(
        source,
        session_id,
    )


def main_key(event: dict) -> str:
    return main_execution_key(
        event["source"],
        event["session_id"],
    )


def _session_key(event: dict) -> str:
    return session_key(
        event["source"],
        event["session_id"],
    )


def _value(
    event: dict,
    name: str,
) -> str:
    value = event.get(name)

    return (
        value
        if isinstance(value, str)
        else ""
    )


def _upsert(
    con: sqlite3.Connection,
    event: dict,
    *,
    state: str,
    parent: str | None = None,
    ended_by: str | None = None,
) -> None:
    key = key_for(event)
    skey = _session_key(event)
    when = _value(event, "t")

    existing = con.execute(
        """
        SELECT atualizado_em
        FROM execucao
        WHERE chave = ?
        """,
        (key,),
    ).fetchone()

    if (
        existing
        and existing["atualizado_em"] > when
    ):
        return

    agent_id = _value(
        event,
        "agent_id",
    )

    kind = (
        _value(event, "agent_type")
        or (
            "subagente"
            if agent_id
            else "principal"
        )
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
        VALUES (
            ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?, ?
        )

        ON CONFLICT(chave)
        DO UPDATE SET
            cwd = CASE
                WHEN excluded.cwd <> ''
                THEN excluded.cwd
                ELSE execucao.cwd
            END,

            estado = excluded.estado,
            origem_encerramento =
                excluded.origem_encerramento,
            atualizado_em =
                excluded.atualizado_em
        """,
        (
            key,
            skey,
            event["source"],
            event["session_id"],
            agent_id or None,
            parent,
            kind,
            _value(event, "cwd"),
            state,
            ended_by,
            when,
            when,
        ),
    )


def _set_main(
    con: sqlite3.Connection,
    event: dict,
    state: str,
    ended_by: str | None = None,
) -> None:
    main = dict(event)

    main.pop("agent_id", None)
    main.pop("agent_type", None)

    _upsert(
        con,
        main,
        state=state,
        ended_by=ended_by,
    )


def _active_children(
    con: sqlite3.Connection,
    event: dict,
) -> int:
    return con.execute(
        """
        SELECT COUNT(*)
        FROM execucao
        WHERE session_key = ?
          AND pai_chave IS NOT NULL
          AND estado IN (
              'trabalhando',
              'delegando',
              'aguardando'
          )
        """,
        (
            _session_key(event),
        ),
    ).fetchone()[0]


def apply(
    con: sqlite3.Connection,
    event: dict,
) -> None:
    name = event["evento"]

    if name == EventName.SESSION_STARTED:
        _set_main(
            con,
            event,
            "aguardando",
        )

    elif name == EventName.TURN_STARTED:
        _set_main(
            con,
            event,
            "trabalhando",
        )

    elif name == EventName.AGENT_STARTED:
        _set_main(
            con,
            event,
            "delegando",
        )

        _upsert(
            con,
            event,
            state="trabalhando",
            parent=main_key(event),
        )

    elif name == EventName.AGENT_FINISHED:
        main_execution = con.execute(
            """
            SELECT 1
            FROM execucao
            WHERE chave = ?
            """,
            (
                main_key(event),
            ),
        ).fetchone()

        if not main_execution:
            _set_main(
                con,
                event,
                "aguardando",
            )

        _upsert(
            con,
            event,
            state="concluida",
            parent=main_key(event),
            ended_by=EventName.AGENT_FINISHED,
        )

        main = con.execute(
            """
            SELECT estado
            FROM execucao
            WHERE chave = ?
            """,
            (
                main_key(event),
            ),
        ).fetchone()

        if (
            main
            and main["estado"] == "delegando"
            and not _active_children(
                con,
                event,
            )
        ):
            _set_main(
                con,
                event,
                "trabalhando",
            )

    elif name == EventName.TURN_FINISHED:
        tasks = event.get(
            "background_tasks"
        )

        if isinstance(tasks, list):
            listed = {
                str(task["id"])
                for task in tasks
                if (
                    isinstance(task, dict)
                    and task.get("id")
                )
            }

            children = con.execute(
                """
                SELECT
                    chave,
                    agent_id
                FROM execucao
                WHERE session_key = ?
                  AND pai_chave IS NOT NULL
                  AND estado IN (
                      'trabalhando',
                      'delegando',
                      'aguardando'
                  )
                """,
                (
                    _session_key(event),
                ),
            ).fetchall()

            for child in children:
                if (
                    child["agent_id"]
                    not in listed
                ):
                    con.execute(
                        """
                        UPDATE execucao
                        SET
                            estado = 'concluida',
                            origem_encerramento =
                                'interrompida',
                            atualizado_em = ?
                        WHERE chave = ?
                          AND atualizado_em <= ?
                        """,
                        (
                            _value(
                                event,
                                "t",
                            ),
                            child["chave"],
                            _value(
                                event,
                                "t",
                            ),
                        ),
                    )

        _set_main(
            con,
            event,
            (
                "delegando"
                if _active_children(
                    con,
                    event,
                )
                else "aguardando"
            ),
        )

    elif name == EventName.SESSION_FINISHED:
        _set_main(
            con,
            event,
            "concluida",
            (
                _value(
                    event,
                    "reason",
                )
                or EventName.SESSION_FINISHED
            ),
        )

        con.execute(
            """
            UPDATE execucao
            SET
                estado = 'concluida',
                origem_encerramento = ?,
                atualizado_em = ?
            WHERE session_key = ?
              AND pai_chave IS NOT NULL
              AND estado IN (
                  'trabalhando',
                  'delegando',
                  'aguardando'
              )
              AND atualizado_em <= ?
            """,
            (
                EventName.SESSION_FINISHED,
                _value(
                    event,
                    "t",
                ),
                _session_key(event),
                _value(
                    event,
                    "t",
                ),
            ),
        )


def event_data(event: dict) -> str:
    safe = {
        key: value
        for key, value in event.items()
        if key
        not in {
            "prompt",
            "last_assistant_message",
        }
    }

    return json.dumps(
        safe,
        ensure_ascii=False,
        sort_keys=True,
    )


def public(
    row: sqlite3.Row,
    project: dict | None,
) -> dict:
    item = dict(row)

    item["projeto_id"] = (
        project["id"]
        if project
        else None
    )

    item["projeto_nome"] = (
        project["nome"]
        if project
        else None
    )

    return item