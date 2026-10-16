from __future__ import annotations

from enum import StrEnum
from typing import NotRequired, TypedDict


class TaskStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING = "waiting"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


FINAL_TASK_STATUSES = {
    TaskStatus.COMPLETED,
    TaskStatus.FAILED,
    TaskStatus.CANCELLED,
}


class TaskRecord(TypedDict):
    id: str
    source: str
    agent: str
    project_id: int | None
    prompt: str
    status: TaskStatus
    provider_session_id: NotRequired[str | None]
    final_output: NotRequired[str | None]
    error: NotRequired[str | None]
    cancel_requested: NotRequired[bool]
    created_at: str
    updated_at: str
