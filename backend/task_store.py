"""Persistence for tasks initiated explicitly through Agent Console."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone

from backend.task_contract import TaskStatus


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ensure_schema(con: sqlite3.Connection) -> None:
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS task (
            id TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            agent TEXT NOT NULL,
            project_id INTEGER,
            prompt TEXT NOT NULL,
            status TEXT NOT NULL
                CHECK (status IN ('queued', 'running', 'waiting', 'completed', 'failed', 'cancelled')),
            provider_session_id TEXT,
            final_output TEXT,
            error TEXT,
            cancel_requested INTEGER NOT NULL DEFAULT 0
                CHECK (cancel_requested IN (0, 1)),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (project_id) REFERENCES projeto(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS task_event (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            source_event TEXT,
            message TEXT,
            data TEXT NOT NULL,
            t TEXT NOT NULL,
            FOREIGN KEY (task_id) REFERENCES task(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_task_updated
            ON task(updated_at DESC);

        CREATE INDEX IF NOT EXISTS idx_task_event_task
            ON task_event(task_id, id);
        """
    )


def _public(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    item = dict(row)
    item["cancel_requested"] = bool(item["cancel_requested"])
    return item


def create_task(
    con: sqlite3.Connection,
    *,
    source: str,
    agent: str,
    prompt: str,
    project_id: int | None = None,
) -> dict:
    ensure_schema(con)
    source = source.strip()
    agent = agent.strip()
    prompt = prompt.strip()
    if not source:
        raise ValueError("source is required")
    if not agent:
        raise ValueError("agent is required")
    if not prompt:
        raise ValueError("prompt is required")
    if project_id is not None:
        exists = con.execute("SELECT 1 FROM projeto WHERE id = ?", (project_id,)).fetchone()
        if exists is None:
            raise ValueError("project not found")

    task_id = str(uuid.uuid4())
    now = utc_now()
    con.execute(
        """
        INSERT INTO task (
            id, source, agent, project_id, prompt, status,
            provider_session_id, final_output, error,
            cancel_requested, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, NULL, 0, ?, ?)
        """,
        (task_id, source, agent, project_id, prompt, TaskStatus.QUEUED, now, now),
    )
    append_event(con, task_id, "task.queued", message="Task queued.", t=now)
    return get_task(con, task_id)


def get_task(con: sqlite3.Connection, task_id: str) -> dict | None:
    ensure_schema(con)
    return _public(con.execute("SELECT * FROM task WHERE id = ?", (task_id,)).fetchone())


def list_tasks(con: sqlite3.Connection, *, limit: int = 50) -> list[dict]:
    ensure_schema(con)
    rows = con.execute(
        "SELECT * FROM task ORDER BY updated_at DESC, created_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [_public(row) for row in rows]


def delete_task(con: sqlite3.Connection, task_id: str) -> bool:
    """Delete one task and its timeline events.

    `PRAGMA foreign_keys = ON` on the shared DB connection makes `task_event`
    rows cascade automatically through the schema's ON DELETE CASCADE.
    """
    ensure_schema(con)
    cursor = con.execute("DELETE FROM task WHERE id = ?", (task_id,))
    return cursor.rowcount > 0


def set_status(
    con: sqlite3.Connection,
    task_id: str,
    status: TaskStatus | str,
    *,
    final_output: str | None = None,
    error: str | None = None,
    provider_session_id: str | None = None,
) -> dict:
    ensure_schema(con)
    value = TaskStatus(status).value
    now = utc_now()
    con.execute(
        """
        UPDATE task
        SET status = ?,
            final_output = CASE WHEN ? IS NOT NULL THEN ? ELSE final_output END,
            error = CASE WHEN ? IS NOT NULL THEN ? ELSE error END,
            provider_session_id = CASE WHEN ? IS NOT NULL THEN ? ELSE provider_session_id END,
            updated_at = ?
        WHERE id = ?
        """,
        (
            value,
            final_output, final_output,
            error, error,
            provider_session_id, provider_session_id,
            now,
            task_id,
        ),
    )
    task = get_task(con, task_id)
    if task is None:
        raise KeyError(task_id)
    return task


def set_provider_session(con: sqlite3.Connection, task_id: str, session_id: str) -> dict:
    ensure_schema(con)
    now = utc_now()
    con.execute(
        "UPDATE task SET provider_session_id = ?, updated_at = ? WHERE id = ?",
        (session_id, now, task_id),
    )
    task = get_task(con, task_id)
    if task is None:
        raise KeyError(task_id)
    return task


def request_cancel(con: sqlite3.Connection, task_id: str) -> dict:
    ensure_schema(con)
    now = utc_now()
    cursor = con.execute(
        "UPDATE task SET cancel_requested = 1, updated_at = ? WHERE id = ?",
        (now, task_id),
    )
    if cursor.rowcount == 0:
        raise KeyError(task_id)
    append_event(con, task_id, "task.cancel_requested", message="Cancellation requested.", t=now)
    return get_task(con, task_id)


def cancel_requested(con: sqlite3.Connection, task_id: str) -> bool:
    ensure_schema(con)
    row = con.execute("SELECT cancel_requested FROM task WHERE id = ?", (task_id,)).fetchone()
    return bool(row and row["cancel_requested"])


def append_event(
    con: sqlite3.Connection,
    task_id: str,
    kind: str,
    *,
    source_event: str | None = None,
    message: str | None = None,
    data: dict | None = None,
    t: str | None = None,
) -> dict:
    ensure_schema(con)
    when = t or utc_now()
    cursor = con.execute(
        """
        INSERT INTO task_event (task_id, kind, source_event, message, data, t)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (task_id, kind, source_event, message, json.dumps(data or {}, ensure_ascii=False), when),
    )
    row = con.execute("SELECT * FROM task_event WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return _event_public(row)


def _event_public(row: sqlite3.Row) -> dict:
    item = dict(row)
    try:
        item["data"] = json.loads(item["data"] or "{}")
    except json.JSONDecodeError:
        item["data"] = {}
    return item


def list_events(
    con: sqlite3.Connection,
    task_id: str,
    *,
    after: int = 0,
    limit: int = 500,
) -> list[dict]:
    ensure_schema(con)
    rows = con.execute(
        """
        SELECT * FROM task_event
        WHERE task_id = ? AND id > ?
        ORDER BY id ASC
        LIMIT ?
        """,
        (task_id, after, limit),
    ).fetchall()
    return [_event_public(row) for row in rows]
