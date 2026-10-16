from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from backend.api import app
from backend.config import events_path
from backend import cli
from backend.cli import (
    install_hooks,
    remove_hooks,
    command,
    seed_demo,
)
from backend.db import connect
from backend.reconcile import reconcile
from backend.events_contract import EventName, EventSource


def add_events(*events: dict) -> None:
    with events_path().open("a", encoding="utf-8") as stream:
        for event in events:
            event.setdefault(
                "source",
                EventSource.CLAUDE_CODE,
            )

            stream.write(
                json.dumps(
                    event,
                    ensure_ascii=False,
                )
                + "\n"
            )


def at(minutes: int = 0) -> str:
    return (
        datetime.now(timezone.utc)
        + timedelta(minutes=minutes)
    ).isoformat(timespec="seconds")


def test_projection_tracks_agents_and_session_end(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv(
        "AI_OPERATIONS_ROOM_DATA_DIR",
        str(tmp_path),
    )

    add_events(
        {
            "id": "1",
            "evento": EventName.SESSION_STARTED,
            "session_id": "one",
            "cwd": "/work/one",
            "t": at(-3),
        },
        {
            "id": "2",
            "evento": EventName.AGENT_STARTED,
            "session_id": "one",
            "agent_id": "a",
            "agent_type": "Explore",
            "cwd": "/work/one",
            "t": at(-2),
        },
        {
            "id": "3",
            "evento": EventName.SESSION_FINISHED,
            "session_id": "one",
            "cwd": "/work/one",
            "reason": "other",
            "t": at(-1),
        },
    )

    with TestClient(app) as client:
        panel = client.get("/api/painel").json()

        states = {
            item["chave"]: item["estado"]
            for item in panel["execucoes"]
        }

        assert states == {
            "claude_code:one:main": "concluida",
            "claude_code:one:agent:a": "concluida",
        }

        assert (
            client
            .get("/api/sessoes/one/historico")
            .json()["eventos"][0]["nome"]
            == EventName.SESSION_FINISHED
        )


def test_ingestion_is_idempotent_and_late_start_does_not_reopen_agent(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv(
        "AI_OPERATIONS_ROOM_DATA_DIR",
        str(tmp_path),
    )

    stopped = {
        "id": "stop",
        "evento": EventName.AGENT_FINISHED,
        "session_id": "one",
        "agent_id": "a",
        "agent_type": "Explore",
        "cwd": "/work/one",
        "t": "2026-10-07T10:02:00+00:00",
    }

    add_events(
        stopped,
        stopped,
        {
            "id": "start",
            "evento": EventName.AGENT_STARTED,
            "session_id": "one",
            "agent_id": "a",
            "agent_type": "Explore",
            "cwd": "/work/one",
            "t": "2026-10-07T10:01:00+00:00",
        },
    )

    with TestClient(app) as client:
        agents = client.get(
            "/api/sessoes/one/agentes"
        ).json()["agentes"]

        agent = next(
            item
            for item in agents
            if item["agent_id"] == "a"
        )

        assert agent["estado"] == "concluida"

        assert (
            len(
                client
                .get("/api/sessoes/one/historico")
                .json()["eventos"]
            )
            == 2
        )


def test_hook_registration_preserves_existing_settings(
    tmp_path,
):
    settings = tmp_path / "settings.json"

    settings.write_text(
        json.dumps(
            {
                "theme": "dark",
                "hooks": {
                    "Stop": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "keep",
                                }
                            ]
                        }
                    ]
                },
            }
        )
    )

    install_hooks(settings)

    registered = json.loads(
        settings.read_text()
    )

    assert registered["theme"] == "dark"
    assert len(
        registered["hooks"]["Stop"]
    ) == 2

    remove_hooks(settings)

    remaining = json.loads(
        settings.read_text()
    )

    assert remaining == {
        "theme": "dark",
        "hooks": {
            "Stop": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": "keep",
                        }
                    ]
                }
            ]
        },
    }


def test_stop_interrupts_missing_child_and_does_not_delegate_shell(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv(
        "AI_OPERATIONS_ROOM_DATA_DIR",
        str(tmp_path),
    )

    add_events(
        {
            "id": "start",
            "evento": EventName.SESSION_STARTED,
            "session_id": "s",
            "cwd": "/work",
            "t": at(-4),
        },
        {
            "id": "prompt",
            "evento": EventName.TURN_STARTED,
            "session_id": "s",
            "cwd": "/work",
            "t": at(-3),
        },
        {
            "id": "child",
            "evento": EventName.AGENT_STARTED,
            "session_id": "s",
            "agent_id": "a",
            "cwd": "/work",
            "t": at(-2),
        },
        {
            "id": "stop",
            "evento": EventName.TURN_FINISHED,
            "session_id": "s",
            "cwd": "/work",
            "background_tasks": [
                {
                    "id": "shell-1",
                    "type": "shell",
                }
            ],
            "t": at(-1),
        },
    )

    with TestClient(app) as client:
        agents = {
            agent["chave"]: agent
            for agent in client
            .get("/api/sessoes/s/agentes")
            .json()["agentes"]
        }

        assert (
            agents["claude_code:s:agent:a"]["estado"]
            == "concluida"
        )

        assert (
            agents["claude_code:s:agent:a"]["origem_encerramento"]
            == "interrompida"
        )

        assert (
            agents["claude_code:s:main"]["estado"]
            == "aguardando"
        )


def test_child_stop_returns_main_to_work_and_missing_list_keeps_child(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv(
        "AI_OPERATIONS_ROOM_DATA_DIR",
        str(tmp_path),
    )

    add_events(
        {
            "id": "start",
            "evento": EventName.AGENT_STARTED,
            "session_id": "s",
            "agent_id": "a",
            "cwd": "/work",
            "t": at(-3),
        },
        {
            "id": "stop",
            "evento": EventName.TURN_FINISHED,
            "session_id": "s",
            "cwd": "/work",
            "t": at(-2),
        },
    )

    with TestClient(app) as client:
        agents = {
            agent["chave"]: agent
            for agent in client
            .get("/api/sessoes/s/agentes")
            .json()["agentes"]
        }

        assert (
            agents["claude_code:s:agent:a"]["estado"]
            == "trabalhando"
        )

        assert (
            agents["claude_code:s:main"]["estado"]
            == "delegando"
        )

        add_events(
            {
                "id": "end",
                "evento": EventName.AGENT_FINISHED,
                "session_id": "s",
                "agent_id": "a",
                "cwd": "/work",
                "t": at(-1),
            }
        )

        agents = {
            agent["chave"]: agent
            for agent in client
            .get("/api/sessoes/s/agentes")
            .json()["agentes"]
        }

        assert (
            agents["claude_code:s:agent:a"]["estado"]
            == "concluida"
        )

        assert (
            agents["claude_code:s:main"]["estado"]
            == "trabalhando"
        )


def test_window_ghost_and_active_session_count(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv(
        "AI_OPERATIONS_ROOM_DATA_DIR",
        str(tmp_path),
    )

    add_events(
        {
            "id": "old",
            "evento": EventName.SESSION_STARTED,
            "session_id": "old",
            "cwd": "/work",
            "t": at(-900),
        },
        {
            "id": "old-end",
            "evento": EventName.SESSION_FINISHED,
            "session_id": "old",
            "cwd": "/work",
            "t": at(-899),
        },
        {
            "id": "ghost",
            "evento": EventName.SESSION_STARTED,
            "session_id": "ghost",
            "cwd": "/work",
            "t": at(-2),
        },
        {
            "id": "ghost-end",
            "evento": EventName.SESSION_FINISHED,
            "session_id": "ghost",
            "cwd": "/work",
            "t": at(-2),
        },
        {
            "id": "live",
            "evento": EventName.SESSION_STARTED,
            "session_id": "live",
            "cwd": "/work",
            "t": at(-1),
        },
        {
            "id": "short-main",
            "evento": EventName.SESSION_STARTED,
            "session_id": "short",
            "cwd": "/work",
            "t": at(-2),
        },
        {
            "id": "short-child",
            "evento": EventName.AGENT_STARTED,
            "session_id": "short",
            "agent_id": "quick",
            "cwd": "/work",
            "t": at(-2),
        },
        {
            "id": "short-end",
            "evento": EventName.SESSION_FINISHED,
            "session_id": "short",
            "cwd": "/work",
            "t": at(-2),
        },
    )

    with TestClient(app) as client:
        panel = client.get(
            "/api/painel"
        ).json()

        assert {
            item["session_id"]
            for item in panel["execucoes"]
        } == {
            "live",
            "short",
        }

        assert (
            len(
                [
                    item
                    for item in panel["execucoes"]
                    if item["session_id"] == "short"
                ]
            )
            == 2
        )

        assert (
            panel["resumo"]["sessoes_ativas"]
            == 1
        )

        assert (
            client
            .get("/api/painel?horas=0")
            .status_code
            == 422
        )


def test_reconcile_dead_pid_and_stale_unknown_session(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv(
        "AI_OPERATIONS_ROOM_DATA_DIR",
        str(tmp_path),
    )

    add_events(
        {
            "id": "a",
            "evento": EventName.SESSION_STARTED,
            "session_id": "dead",
            "cwd": "/work",
            "t": at(-1),
        },
        {
            "id": "b",
            "evento": EventName.SESSION_STARTED,
            "session_id": "unknown",
            "cwd": "/work",
            "t": at(-11),
        },
        {
            "id": "c",
            "evento": EventName.SESSION_STARTED,
            "session_id": "alive",
            "cwd": "/work",
            "t": at(-11),
        },
    )

    with TestClient(app) as client:
        client.get("/api/sessoes")

        with connect() as con:
            assert (
                reconcile(
                    con,
                    living={
                        "dead": False,
                        "alive": True,
                    },
                    now=datetime.now(
                        timezone.utc
                    ),
                )
                == 2
            )

        agents = client.get(
            "/api/sessoes/dead/agentes"
        ).json()["agentes"]

        assert (
            agents[0]["estado"]
            == "orfa"
        )

        assert (
            client
            .get("/api/sessoes/alive/agentes")
            .json()["agentes"][0]["estado"]
            == "aguardando"
        )


def test_queue_rotation_with_larger_replacement(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv(
        "AI_OPERATIONS_ROOM_DATA_DIR",
        str(tmp_path),
    )

    add_events(
        {
            "id": "a",
            "evento": EventName.SESSION_STARTED,
            "session_id": "a",
            "cwd": "/a",
            "t": at(-2),
        }
    )

    with TestClient(app) as client:
        assert (
            len(
                client
                .get("/api/sessoes")
                .json()["sessoes"]
            )
            == 1
        )

        replacement = [
            {
                "id": f"new-{i}",
                "evento": EventName.SESSION_STARTED,
                "source": EventSource.CLAUDE_CODE,
                "session_id": f"new-{i}",
                "cwd": "/new",
                "t": at(-1),
            }
            for i in range(3)
        ]

        events_path().write_text(
            "".join(
                json.dumps(
                    event,
                    ensure_ascii=False,
                )
                + "\n"
                for event in replacement
            ),
            encoding="utf-8",
        )

        assert (
            len(
                client
                .get("/api/sessoes")
                .json()["sessoes"]
            )
            == 4
        )


def test_hook_settings_bom_and_changed_python(
    tmp_path,
):
    if os.name == "nt":
        assert command().startswith("& ")

    settings = tmp_path / "settings.json"

    settings.write_text(
        '{"theme":"dark"}',
        encoding="utf-8-sig",
    )

    install_hooks(settings)

    assert settings.read_bytes().startswith(
        b"\xef\xbb\xbf"
    )

    data = json.loads(
        settings.read_text(
            encoding="utf-8-sig",
        )
    )

    hook = data["hooks"]["Stop"][0]["hooks"][0]

    assert (
        hook.get("shell")
        == (
            "powershell"
            if os.name == "nt"
            else None
        )
    )

    hook["command"] = hook[
        "command"
    ].replace(
        command().split('"')[1],
        "C:/other/python.exe",
    )

    settings.write_text(
        json.dumps(data),
        encoding="utf-8-sig",
    )

    remove_hooks(settings)

    assert (
        json.loads(
            settings.read_text(
                encoding="utf-8-sig",
            )
        )
        == {
            "theme": "dark",
        }
    )


def test_registered_hook_runs_in_its_declared_shell(
    tmp_path,
):
    settings = tmp_path / "settings.json"

    install_hooks(settings)

    hook = json.loads(
        settings.read_text(
            encoding="utf-8",
        )
    )["hooks"]["SessionStart"][0]["hooks"][0]

    if hook.get("shell") == "powershell":
        executable = (
            shutil.which("powershell.exe")
            or shutil.which("pwsh.exe")
        )

        assert (
            executable
        ), "PowerShell necessário para validar o hook registrado"

        args = [
            executable,
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            hook["command"],
        ]

    else:
        args = [
            "bash",
            "-c",
            hook["command"],
        ]

    env = os.environ.copy()

    env[
        "AI_OPERATIONS_ROOM_DATA_DIR"
    ] = str(tmp_path)

    result = subprocess.run(
        args,
        input=json.dumps(
            {
                "hook_event_name": "SessionStart",
                "session_id": "shell-check",
                "cwd": "/work",
            }
        ),
        text=True,
        capture_output=True,
        env=env,
        timeout=15,
    )

    assert result.returncode == 0, result.stderr

    saved = [
        json.loads(line)
        for line in (
            tmp_path / "events.jsonl"
        )
        .read_text(
            encoding="utf-8"
        )
        .splitlines()
    ]

    assert (
        saved[0]["session_id"]
        == "shell-check"
    )

    assert (
        saved[0]["evento"]
        == EventName.SESSION_STARTED
    )

    assert (
        saved[0]["source"]
        == EventSource.CLAUDE_CODE
    )

    assert (
        saved[0]["source_event"]
        == "SessionStart"
    )


def test_install_repairs_existing_hook_without_shell(
    tmp_path,
):
    settings = tmp_path / "settings.json"

    settings.write_text(
        json.dumps(
            {
                "hooks": {
                    "Stop": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": command(),
                                    "timeout": 5,
                                }
                            ]
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    install_hooks(settings)

    hooks = json.loads(
        settings.read_text(
            encoding="utf-8"
        )
    )["hooks"]["Stop"]

    assert len(hooks) == 1

    assert (
        hooks[0]["hooks"][0].get("shell")
        == (
            "powershell"
            if os.name == "nt"
            else None
        )
    )


def test_demo_stays_active_and_reseeding_refreshes_timestamps(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv(
        "AI_OPERATIONS_ROOM_DATA_DIR",
        str(tmp_path),
    )

    seed_demo(tmp_path)

    with TestClient(app) as client:
        first = client.get(
            "/api/painel"
        ).json()

        atlas = next(
            item
            for item in first["execucoes"]
            if (
                item["session_id"]
                == "demo-atlas"
                and not item["pai_chave"]
            )
        )

        original_start = atlas["criado_em"]

        with connect() as con:
            con.execute(
                "UPDATE execucao "
                "SET atualizado_em = ? "
                "WHERE session_id = 'demo-atlas'",
                (
                    at(-30),
                ),
            )

        stable = client.get(
            "/api/painel"
        ).json()

        assert any(
            item["session_id"] == "demo-atlas"
            and item["estado"] == "delegando"
            for item in stable["execucoes"]
        )

        events = cli.demo_events()

        monkeypatch.setattr(
            cli,
            "demo_events",
            lambda: [
                {
                    **event,
                    "t": at(-1),
                }
                for event in events
            ],
        )

        seed_demo(tmp_path)

        renewed = client.get(
            "/api/painel"
        ).json()

        atlas = next(
            item
            for item in renewed["execucoes"]
            if (
                item["session_id"]
                == "demo-atlas"
                and not item["pai_chave"]
            )
        )

        assert (
            atlas["criado_em"]
            != original_start
        )