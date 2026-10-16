"""Projection of normalized events into session and agent states."""

from __future__ import annotations

import json
import sqlite3

from backend.events_contract import EventName


ACTIVE = {
    "trabalhando",
    "delegando",
    "aguardando",
}


def key_for(event: dict) -> str:
    agent_id = event.get("agent_id")

    if isinstance(agent_id, str) and agent_id:
        return f"agent:{agent_id}"

    return f"session:{event['session_id']}"


def main_key(session_id: str) -> str:
    return f"session:{session_id}"


def _value(event: dict, name: str) -> str:
    value = event.get(name)

    return value if isinstance(value, str) else ""


def _upsert(
    con: sqlite3.Connection,
    event: dict,
    *,
    state: str,
    parent: str | None = None,
    ended_by: str | None = None,
) -> None:
    key = key_for(event)
    when = _value(event, "t")

    existing = con.execute(
        "SELECT atualizado_em "
        "FROM execucao "
        "WHERE chave = ?",
        (key,),
    ).fetchone()

    if (
        existing
        and existing["atualizado_em"] > when
    ):
        return

    kind = (
        _value(event, "agent_type")
        or (
            "principal"
            if key.startswith("session:")
            else "subagente"
        )
    )

    con.execute(
        "INSERT INTO execucao "
        "(chave, session_id, agent_id, pai_chave, "
        "tipo, cwd, estado, origem_encerramento, "
        "criado_em, atualizado_em) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(chave) DO UPDATE SET "
        "cwd = CASE "
        "WHEN excluded.cwd <> '' "
        "THEN excluded.cwd "
        "ELSE execucao.cwd END, "
        "estado = excluded.estado, "
        "origem_encerramento = "
        "excluded.origem_encerramento, "
        "atualizado_em = excluded.atualizado_em",
        (
            key,
            event["session_id"],
            _value(event, "agent_id") or None,
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
    session_id: str,
) -> int:
    return con.execute(
        "SELECT COUNT(*) "
        "FROM execucao "
        "WHERE session_id = ? "
        "AND pai_chave IS NOT NULL "
        "AND estado IN "
        "('trabalhando', 'delegando', 'aguardando')",
        (session_id,),
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
            parent=main_key(
                event["session_id"]
            ),
        )

    elif name == EventName.AGENT_FINISHED:
        main_execution = con.execute(
            "SELECT 1 "
            "FROM execucao "
            "WHERE chave = ?",
            (
                main_key(
                    event["session_id"]
                ),
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
            parent=main_key(
                event["session_id"]
            ),
            ended_by=EventName.AGENT_FINISHED,
        )

        main = con.execute(
            "SELECT estado "
            "FROM execucao "
            "WHERE chave = ?",
            (
                main_key(
                    event["session_id"]
                ),
            ),
        ).fetchone()

        if (
            main
            and main["estado"] == "delegando"
            and not _active_children(
                con,
                event["session_id"],
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
                "SELECT chave, agent_id "
                "FROM execucao "
                "WHERE session_id = ? "
                "AND pai_chave IS NOT NULL "
                "AND estado IN "
                "('trabalhando', "
                "'delegando', "
                "'aguardando')",
                (
                    event["session_id"],
                ),
            ).fetchall()

            for child in children:
                if child["agent_id"] not in listed:
                    con.execute(
                        "UPDATE execucao "
                        "SET estado = 'concluida', "
                        "origem_encerramento = "
                        "'interrompida', "
                        "atualizado_em = ? "
                        "WHERE chave = ? "
                        "AND atualizado_em <= ?",
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
                    event["session_id"],
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
            "UPDATE execucao "
            "SET estado = 'concluida', "
            "origem_encerramento = ?, "
            "atualizado_em = ? "
            "WHERE session_id = ? "
            "AND pai_chave IS NOT NULL "
            "AND estado IN "
            "('trabalhando', "
            "'delegando', "
            "'aguardando') "
            "AND atualizado_em <= ?",
            (
                EventName.SESSION_FINISHED,
                _value(
                    event,
                    "t",
                ),
                event["session_id"],
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