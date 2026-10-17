"""Provider-neutral execution engine for Agent Console tasks."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Callable, Protocol

from backend.db import connect
from backend.task_contract import FINAL_TASK_STATUSES, TaskStatus
from backend import task_store


Emit = Callable[..., None]
CancelCheck = Callable[[], bool]


@dataclass(slots=True)
class ProviderResult:
    output: str
    provider_session_id: str | None = None


class TaskCancelled(RuntimeError):
    pass


class TaskProvider(Protocol):
    source: str

    def available(self) -> bool: ...
    def unavailable_reason(self) -> str | None: ...
    def run(self, task: dict, emit: Emit, is_cancelled: CancelCheck) -> ProviderResult: ...


_PROVIDERS: dict[str, TaskProvider] = {}
_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="ai-room-task")


def register_provider(provider: TaskProvider) -> None:
    _PROVIDERS[provider.source] = provider


def unregister_provider(source: str) -> None:
    _PROVIDERS.pop(source, None)


def get_provider(source: str) -> TaskProvider | None:
    return _PROVIDERS.get(source)


def provider_statuses() -> list[dict]:
    result = []
    for source, provider in sorted(_PROVIDERS.items()):
        available = provider.available()
        result.append({
            "source": source,
            "available": available,
            "reason": None if available else provider.unavailable_reason(),
        })
    return result


def _emit(task_id: str, kind: str, **kwargs) -> None:
    with connect() as con:
        task_store.append_event(con, task_id, kind, **kwargs)
        if kind == "provider.session":
            session_id = (kwargs.get("data") or {}).get("provider_session_id")
            if isinstance(session_id, str) and session_id:
                task_store.set_provider_session(con, task_id, session_id)


def _is_cancelled(task_id: str) -> bool:
    with connect() as con:
        return task_store.cancel_requested(con, task_id)


def _finish(
    task_id: str,
    status: TaskStatus,
    *,
    output: str | None = None,
    error: str | None = None,
    provider_session_id: str | None = None,
) -> None:
    with connect() as con:
        task_store.set_status(
            con,
            task_id,
            status,
            final_output=output,
            error=error,
            provider_session_id=provider_session_id,
        )
        task_store.append_event(
            con,
            task_id,
            f"task.{status.value}",
            message=error or ("Task completed." if status == TaskStatus.COMPLETED else None),
        )


def run_task(task_id: str) -> None:
    with connect() as con:
        task = task_store.get_task(con, task_id)
    if task is None:
        return
    if TaskStatus(task["status"]) in FINAL_TASK_STATUSES:
        return
    if task.get("cancel_requested"):
        _finish(task_id, TaskStatus.CANCELLED)
        return

    provider = get_provider(task["source"])
    if provider is None:
        _finish(task_id, TaskStatus.FAILED, error=f"No provider registered for {task['source']}")
        return
    if not provider.available():
        _finish(
            task_id,
            TaskStatus.FAILED,
            error=provider.unavailable_reason() or f"Provider {task['source']} is unavailable",
        )
        return

    with connect() as con:
        task_store.set_status(con, task_id, TaskStatus.RUNNING)
        task_store.append_event(con, task_id, "task.running", message="Task started.")
        task = task_store.get_task(con, task_id)

    try:
        result = provider.run(
            task,
            lambda kind, **kwargs: _emit(task_id, kind, **kwargs),
            lambda: _is_cancelled(task_id),
        )
        if _is_cancelled(task_id):
            _finish(
                task_id,
                TaskStatus.CANCELLED,
                output=result.output or None,
                provider_session_id=result.provider_session_id,
            )
        else:
            _finish(
                task_id,
                TaskStatus.COMPLETED,
                output=result.output,
                provider_session_id=result.provider_session_id,
            )
    except TaskCancelled:
        _finish(task_id, TaskStatus.CANCELLED)
    except Exception as exc:
        _finish(task_id, TaskStatus.FAILED, error=str(exc))


def submit_task(task_id: str) -> None:
    _EXECUTOR.submit(run_task, task_id)


def _register_defaults() -> None:
    from backend.providers.codex_local import CodexTaskProvider
    from backend.providers.ollama_local import OllamaTaskProvider
    from backend.providers.openai_agents import OpenAIAgentsProvider

    register_provider(CodexTaskProvider())
    register_provider(OllamaTaskProvider())
    register_provider(OpenAIAgentsProvider())


_register_defaults()
