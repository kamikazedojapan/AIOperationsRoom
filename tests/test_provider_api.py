from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from backend.api import app
from backend.config import events_path
from backend.events_contract import EventName, EventSource


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_OPERATIONS_ROOM_DATA_DIR", str(tmp_path))
    with TestClient(app) as test_client:
        yield test_client


def write_events(*events: dict) -> None:
    with events_path().open("a", encoding="utf-8") as stream:
        for event in events:
            stream.write(json.dumps(event) + "\n")


def provider_events() -> tuple[dict, dict]:
    now = datetime.now(timezone.utc)
    return (
        {
            "id": "claude-1",
            "evento": EventName.SESSION_STARTED,
            "source": EventSource.CLAUDE_CODE,
            "session_id": "shared",
            "cwd": "/claude",
            "t": (now - timedelta(seconds=2)).isoformat(timespec="seconds"),
        },
        {
            "id": "codex-1",
            "evento": EventName.SESSION_STARTED,
            "source": EventSource.CODEX,
            "session_id": "shared",
            "cwd": "/codex",
            "t": (now - timedelta(seconds=1)).isoformat(timespec="seconds"),
        },
    )


def test_session_list_exposes_provider_identity(client: TestClient):
    write_events(*provider_events())
    response = client.get("/api/sessoes")
    assert response.status_code == 200

    sessions = {
        item["session_key"]: item
        for item in response.json()["sessoes"]
    }
    assert "claude_code:shared" in sessions
    assert "codex:shared" in sessions
    assert sessions["claude_code:shared"]["source"] == "claude_code"
    assert sessions["codex:shared"]["source"] == "codex"


def test_history_is_isolated_by_provider(client: TestClient):
    write_events(*provider_events())

    claude = client.get("/api/sessoes/claude_code/shared/historico")
    codex = client.get("/api/sessoes/codex/shared/historico")

    assert claude.status_code == 200
    assert codex.status_code == 200
    assert [item["source"] for item in claude.json()["eventos"]] == ["claude_code"]
    assert [item["source"] for item in codex.json()["eventos"]] == ["codex"]


def test_agents_are_isolated_by_provider(client: TestClient):
    write_events(*provider_events())

    claude = client.get("/api/sessoes/claude_code/shared/agentes")
    codex = client.get("/api/sessoes/codex/shared/agentes")

    assert claude.status_code == 200
    assert codex.status_code == 200
    assert [item["session_key"] for item in claude.json()["agentes"]] == [
        "claude_code:shared"
    ]
    assert [item["session_key"] for item in codex.json()["agentes"]] == [
        "codex:shared"
    ]


def test_legacy_route_rejects_ambiguous_native_session_id(client: TestClient):
    write_events(*provider_events())
    response = client.get("/api/sessoes/shared/agentes")
    assert response.status_code == 409


def test_active_session_count_uses_provider_identity(client: TestClient):
    write_events(*provider_events())
    panel = client.get("/api/painel").json()
    assert panel["resumo"]["sessoes_ativas"] == 2
