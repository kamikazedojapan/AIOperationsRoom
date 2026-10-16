from __future__ import annotations

from backend.db import connect, init_db
from backend.task_contract import TaskStatus
from backend import task_runner, task_store
from backend.task_runner import ProviderResult


class FakeProvider:
    source = "openai_api"

    def available(self) -> bool:
        return True

    def unavailable_reason(self) -> str | None:
        return None

    def run(self, task, emit, is_cancelled):
        emit("provider.lifecycle", source_event="fake.started", data={"event": "turn.started"})
        emit("provider.session", data={"provider_session_id": "sess-fake"})
        emit("output.delta", message="hello ")
        emit("output.delta", message="world")
        return ProviderResult(output="hello world", provider_session_id="sess-fake")


def setup_room(monkeypatch, tmp_path):
    monkeypatch.setenv("AI_OPERATIONS_ROOM_DATA_DIR", str(tmp_path))
    init_db()
    original = task_runner.get_provider("openai_api")
    task_runner.register_provider(FakeProvider())
    return original


def restore_provider(original):
    if original is None:
        task_runner.unregister_provider("openai_api")
    else:
        task_runner.register_provider(original)


def test_run_task_completes_and_persists_timeline(monkeypatch, tmp_path):
    original = setup_room(monkeypatch, tmp_path)
    try:
        with connect() as con:
            task = task_store.create_task(
                con,
                source="openai_api",
                agent="general",
                prompt="do the task",
            )

        task_runner.run_task(task["id"])

        with connect() as con:
            saved = task_store.get_task(con, task["id"])
            events = task_store.list_events(con, task["id"])

        assert saved["status"] == TaskStatus.COMPLETED
        assert saved["final_output"] == "hello world"
        assert saved["provider_session_id"] == "sess-fake"
        assert [event["kind"] for event in events] == [
            "task.queued",
            "task.running",
            "provider.lifecycle",
            "provider.session",
            "output.delta",
            "output.delta",
            "task.completed",
        ]
    finally:
        restore_provider(original)


def test_cancel_flag_is_provider_neutral(monkeypatch, tmp_path):
    original = setup_room(monkeypatch, tmp_path)
    try:
        with connect() as con:
            task = task_store.create_task(
                con,
                source="openai_api",
                agent="general",
                prompt="do the task",
            )
            task_store.request_cancel(con, task["id"])

        task_runner.run_task(task["id"])

        with connect() as con:
            saved = task_store.get_task(con, task["id"])
            events = task_store.list_events(con, task["id"])

        assert saved["status"] == TaskStatus.CANCELLED
        assert events[-1]["kind"] == "task.cancelled"
    finally:
        restore_provider(original)
