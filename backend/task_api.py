"""HTTP surface for Agent Console tasks."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from backend.config import FRONTEND
from backend.db import connect
from backend.task_contract import FINAL_TASK_STATUSES, TaskStatus
from backend import task_store
from backend.task_runner import get_provider, provider_statuses, submit_task


router = APIRouter()


class TaskInput(BaseModel):
    source: str = Field(min_length=1, max_length=64)
    agent: str = Field(min_length=1, max_length=64)
    prompt: str = Field(min_length=1, max_length=100_000)
    project_id: int | None = None


def database():
    with connect() as con:
        yield con


@router.get("/api/task-providers")
def task_providers() -> dict:
    return {
        "providers": provider_statuses(),
        "agents": ["general", "coder", "reviewer"],
    }


@router.get("/api/tasks")
def list_tasks(
    limit: int = Query(50, ge=1, le=200),
    con: sqlite3.Connection = Depends(database),
) -> dict:
    return {"tasks": task_store.list_tasks(con, limit=limit)}


@router.post("/api/tasks", status_code=status.HTTP_202_ACCEPTED)
def create_task(
    data: TaskInput,
    con: sqlite3.Connection = Depends(database),
) -> dict:
    source = data.source.strip()
    provider = get_provider(source)
    if provider is None:
        raise HTTPException(status_code=422, detail=f"Provider não registrado: {source}")
    if not provider.available():
        raise HTTPException(
            status_code=503,
            detail=provider.unavailable_reason() or f"Provider indisponível: {source}",
        )

    try:
        task = task_store.create_task(
            con,
            source=source,
            agent=data.agent,
            prompt=data.prompt,
            project_id=data.project_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # The runner opens a different SQLite connection. Commit before scheduling so
    # the worker can always see the newly-created task.
    con.commit()
    submit_task(task["id"])
    return task


@router.get("/api/tasks/{task_id}")
def get_task(
    task_id: str,
    con: sqlite3.Connection = Depends(database),
) -> dict:
    task = task_store.get_task(con, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task não encontrada.")
    return task


@router.get("/api/tasks/{task_id}/events")
def task_events(
    task_id: str,
    after: int = Query(0, ge=0),
    con: sqlite3.Connection = Depends(database),
) -> dict:
    task = task_store.get_task(con, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task não encontrada.")
    events = task_store.list_events(con, task_id, after=after)
    return {"events": events}


@router.post("/api/tasks/{task_id}/cancel")
def cancel_task(
    task_id: str,
    con: sqlite3.Connection = Depends(database),
) -> dict:
    task = task_store.get_task(con, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task não encontrada.")
    if TaskStatus(task["status"]) in FINAL_TASK_STATUSES:
        return task
    return task_store.request_cancel(con, task_id)


@router.get("/agent-console")
def agent_console_page() -> FileResponse:
    return FileResponse(FRONTEND / "agent-console.html")
