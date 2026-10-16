from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import backend.task_api as task_api
from backend.api import app
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

    assert providers["fake_provider"]["available"] is True
    assert "coder" in payload["agents"]


def test_agent_console_page_is_served(client: TestClient):
    response = client.get("/agent-console")
    assert response.status_code == 200
    assert "Agent Console" in response.text
