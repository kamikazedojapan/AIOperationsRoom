from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import backend.task_api as task_api
from backend import task_store
from backend.api import app
from backend.db import connect
from backend.task_runner import (
    ProviderResult,
    register_provider,
    run_task,
    unregister_provider,
)


class FakeProvider:
    source = "fake_provider"

    def available(self) -> bool:
        return True

    def unavailable_reason(self) -> str | None:
        return None

    def models(self) -> list[str]:
        return ["fake-small", "fake-large"]

    def run(self, task: dict, emit, is_cancelled) -> ProviderResult:
        emit(
            "provider.session",
            source_event="fake.session.created",
            data={"provider_session_id": "fake-session-1"},
        )
        emit(
            "provider.lifecycle",
            source_event="fake.turn.started",
            data={"event": "turn.started"},
        )
        emit(
            "output.delta",
            source_event="fake.output.delta",
            message="working",
        )
        return ProviderResult(
            output=f"done: {task['prompt']}",
            provider_session_id="fake-session-1",
        )


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv(
        "AI_OPERATIONS_ROOM_DATA_DIR",
        str(tmp_path),
    )
    register_provider(FakeProvider())
    monkeypatch.setattr(
        task_api,
        "submit_task",
        run_task,
    )

    with TestClient(app) as test_client:
        yield test_client

    unregister_provider("fake_provider")


def test_task_runs_through_provider_neutral_api(client: TestClient):
    response = client.post(
        "/api/tasks",
        json={
            "source": "fake_provider",
            "agent": "coder",
            "prompt": "build it",
        },
    )

    assert response.status_code == 202
    task_id = response.json()["id"]

    task = client.get(
        f"/api/tasks/{task_id}"
    ).json()

    assert task["status"] == "completed"
    assert task["source"] == "fake_provider"
    assert task["agent"] == "coder"
    assert task["model"] is None
    assert task["provider_session_id"] == "fake-session-1"
    assert task["final_output"] == "done: build it"

    events = client.get(
        f"/api/tasks/{task_id}/events"
    ).json()["events"]

    kinds = [event["kind"] for event in events]
    assert kinds == [
        "task.queued",
        "task.running",
        "provider.session",
        "provider.lifecycle",
        "output.delta",
        "task.completed",
    ]


def test_event_cursor_returns_only_newer_events(client: TestClient):
    response = client.post(
        "/api/tasks",
        json={
            "source": "fake_provider",
            "agent": "general",
            "prompt": "hello",
        },
    )
    task_id = response.json()["id"]

    events = client.get(
        f"/api/tasks/{task_id}/events"
    ).json()["events"]
    cursor = events[-2]["id"]

    newer = client.get(
        f"/api/tasks/{task_id}/events?after={cursor}"
    ).json()["events"]

    assert [event["kind"] for event in newer] == [
        "task.completed",
    ]


def test_unknown_provider_is_rejected(client: TestClient):
    response = client.post(
        "/api/tasks",
        json={
            "source": "does_not_exist",
            "agent": "general",
            "prompt": "hello",
        },
    )

    assert response.status_code == 422


def test_provider_catalog_exposes_registered_provider(client: TestClient):
    payload = client.get(
        "/api/task-providers"
    ).json()

    providers = {
        item["source"]: item
        for item in payload["providers"]
    }

    fake = providers["fake_provider"]
    assert fake["available"] is True
    assert fake["models"] == ["fake-small", "fake-large"]
    assert fake["capabilities"]["streaming"] is True
    assert fake["capabilities"]["cancel"] is True
    assert fake["capabilities"]["model_selection"] is True
    assert "coder" in payload["agents"]


def test_selected_model_is_persisted(client: TestClient):
    response = client.post(
        "/api/tasks",
        json={
            "source": "fake_provider",
            "agent": "general",
            "prompt": "hello model",
            "model": "fake-large",
        },
    )

    assert response.status_code == 202
    task_id = response.json()["id"]
    task = client.get(f"/api/tasks/{task_id}").json()
    assert task["model"] == "fake-large"


def test_unknown_model_is_rejected(client: TestClient):
    response = client.post(
        "/api/tasks",
        json={
            "source": "fake_provider",
            "agent": "general",
            "prompt": "hello model",
            "model": "missing-model",
        },
    )

    assert response.status_code == 422
    assert "Modelo não disponível" in response.json()["detail"]


def test_completed_task_can_be_deleted_with_timeline(client: TestClient):
    response = client.post(
        "/api/tasks",
        json={
            "source": "fake_provider",
            "agent": "general",
            "prompt": "temporary task",
        },
    )
    task_id = response.json()["id"]

    assert client.get(f"/api/tasks/{task_id}").json()["status"] == "completed"

    deleted = client.delete(f"/api/tasks/{task_id}")
    assert deleted.status_code == 200
    assert deleted.json() == {"deleted": task_id}
    assert client.get(f"/api/tasks/{task_id}").status_code == 404

    with connect() as con:
        event_count = con.execute(
            "SELECT COUNT(*) FROM task_event WHERE task_id = ?",
            (task_id,),
        ).fetchone()[0]
    assert event_count == 0


def test_active_task_cannot_be_deleted(client: TestClient, monkeypatch):
    monkeypatch.setattr(task_api, "submit_task", lambda task_id: None)
    response = client.post(
        "/api/tasks",
        json={
            "source": "fake_provider",
            "agent": "general",
            "prompt": "keep running",
        },
    )
    task_id = response.json()["id"]

    task = client.get(f"/api/tasks/{task_id}").json()
    assert task["status"] == "queued"

    deleted = client.delete(f"/api/tasks/{task_id}")
    assert deleted.status_code == 409
    assert "ainda está ativa" in deleted.json()["detail"]
    assert client.get(f"/api/tasks/{task_id}").status_code == 200


def test_cancelled_stale_task_is_recovered_and_deletable(client: TestClient, monkeypatch):
    monkeypatch.setattr(task_api, "submit_task", lambda task_id: None)
    response = client.post(
        "/api/tasks",
        json={
            "source": "fake_provider",
            "agent": "general",
            "prompt": "cancel then restart",
        },
    )
    task_id = response.json()["id"]

    cancel = client.post(f"/api/tasks/{task_id}/cancel")
    assert cancel.status_code == 200
    assert cancel.json()["cancel_requested"] is True
    assert cancel.json()["status"] == "queued"

    with connect() as con:
        assert task_store.recover_interrupted_tasks(con) == [task_id]

    recovered = client.get(f"/api/tasks/{task_id}").json()
    assert recovered["status"] == "cancelled"
    assert client.delete(f"/api/tasks/{task_id}").status_code == 200


def test_agent_console_page_is_served(client: TestClient):
    response = client.get("/agent-console")
    assert response.status_code == 200
    assert "Agent Console" in response.text
    assert 'id="task-model-field"' in response.text
    assert 'id="task-model"' in response.text
