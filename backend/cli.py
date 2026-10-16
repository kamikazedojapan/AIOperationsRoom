"""Command line entry points for local setup and the isolated demo."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.config import ROOT
from backend.events_contract import EventName, EventSource


EVENTS = (
    "SessionStart",
    "UserPromptSubmit",
    "Stop",
    "SubagentStart",
    "SubagentStop",
    "SessionEnd",
)

CODEX_EVENTS = EVENTS
CODEX_SESSION_START_MATCHER = "^(startup|resume|clear|fork)$"
CODEX_STATUS_MESSAGE = "AI Operations Room telemetry"


def settings_path() -> Path:
    return Path.home() / ".claude" / "settings.json"


def codex_hooks_path() -> Path:
    return Path.home() / ".codex" / "hooks.json"


def codex_wrapper_path() -> Path:
    return Path.home() / ".ai-operations-room" / "codex-hook.cmd"


def command() -> str:
    invocation = f'"{sys.executable}" "{ROOT / "hooks" / "capture.py"}"'
    return f"& {invocation}" if os.name == "nt" else invocation


def write_codex_wrapper(path: Path | None = None) -> Path:
    """Write the Windows shim used by Codex command hooks.

    Current Codex Windows hook parsing is more reliable when the hook command
    itself contains no quoted executable path. The shim keeps the configured
    hook simple while still safely quoting Python and the capture script.
    """
    target = path or codex_wrapper_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    python = os.path.abspath(sys.executable)
    script = str(ROOT / "hooks" / "codex_capture.py")
    content = (
        "@echo off\r\n"
        f'"{python}" "{script}"\r\n'
        "exit /b %ERRORLEVEL%\r\n"
    )
    target.write_bytes(content.encode("utf-8"))
    return target


def codex_command(
    *,
    windows: bool | None = None,
    wrapper_path: Path | None = None,
) -> str:
    if windows is None:
        windows = os.name == "nt"

    if windows:
        wrapper = wrapper_path or codex_wrapper_path()
        return f"cmd.exe /d /s /c {wrapper}"

    python = os.path.abspath(sys.executable)
    script = str(ROOT / "hooks" / "codex_capture.py")
    return f'"{python}" "{script}"'


def _command_targets(value: object, script: Path) -> bool:
    if not isinstance(value, str):
        return False
    expected = os.path.normcase(os.path.normpath(str(script)))
    for candidate in re.findall(r'"([^"]+)"', value):
        actual = os.path.normcase(os.path.normpath(candidate))
        if actual == expected:
            return True
    return False


def _our_hook(item: dict) -> bool:
    return _command_targets(item.get("command"), ROOT / "hooks" / "capture.py")


def _our_codex_hook(item: dict) -> bool:
    if item.get("statusMessage") == CODEX_STATUS_MESSAGE:
        return True

    script = ROOT / "hooks" / "codex_capture.py"
    return any(
        _command_targets(item.get(field), script)
        for field in ("command", "commandWindows", "command_windows")
    )


def load_settings(path: Path, label: str = "Claude Code") -> dict:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError(f"O arquivo de configurações do {label} precisa ser um objeto JSON.")
    return data


def save_settings(path: Path, settings: dict, *, preserve_bom: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoding = (
        "utf-8-sig"
        if preserve_bom
        and path.exists()
        and path.read_bytes().startswith(b"\xef\xbb\xbf")
        else "utf-8"
    )
    path.write_text(
        json.dumps(settings, ensure_ascii=False, indent=2) + "\n",
        encoding=encoding,
    )


def install_hooks(path: Path) -> None:
    settings = load_settings(path)
    hooks = settings.setdefault("hooks", {})
    for event in EVENTS:
        groups = hooks.setdefault(event, [])
        found = False
        for group in groups:
            for item in group.get("hooks", []):
                if _our_hook(item):
                    item["command"] = command()
                    if os.name == "nt":
                        item["shell"] = "powershell"
                    else:
                        item.pop("shell", None)
                    found = True
        if not found:
            hook = {"type": "command", "command": command(), "timeout": 5}
            if os.name == "nt":
                hook["shell"] = "powershell"
            groups.append({"hooks": [hook]})
    save_settings(path, settings)
    print(f"Hooks registrados em {path}")


def remove_hooks(path: Path) -> None:
    settings = load_settings(path)
    hooks = settings.get("hooks", {})
    for event in EVENTS:
        groups = hooks.get(event, [])
        remaining = []
        for group in groups:
            kept = [item for item in group.get("hooks", []) if not _our_hook(item)]
            if kept:
                remaining.append({**group, "hooks": kept})
        if remaining:
            hooks[event] = remaining
        else:
            hooks.pop(event, None)
    if not hooks:
        settings.pop("hooks", None)
    save_settings(path, settings)
    print(f"Hooks removidos de {path}")


def _configure_codex_hook(
    item: dict,
    event: str,
    *,
    invocation: str | None = None,
) -> None:
    invocation = invocation or codex_command()
    item.update(
        {
            "type": "command",
            "command": invocation,
            "commandWindows": invocation,
            "timeout": 3 if event == "SessionEnd" else 5,
            "statusMessage": CODEX_STATUS_MESSAGE,
        }
    )


def install_codex_hooks(path: Path) -> None:
    settings = load_settings(path, "Codex")
    hooks = settings.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError("A chave `hooks` do Codex precisa ser um objeto JSON.")

    if os.name == "nt":
        write_codex_wrapper()
    invocation = codex_command()

    for event in CODEX_EVENTS:
        groups = hooks.setdefault(event, [])
        if not isinstance(groups, list):
            raise ValueError(f"A configuração de hooks `{event}` do Codex precisa ser uma lista.")

        found = False
        for group in groups:
            if not isinstance(group, dict):
                continue
            items = group.get("hooks", [])
            if not isinstance(items, list):
                continue
            for item in items:
                if isinstance(item, dict) and _our_codex_hook(item):
                    _configure_codex_hook(item, event, invocation=invocation)
                    if event == "SessionStart":
                        group["matcher"] = CODEX_SESSION_START_MATCHER
                    found = True

        if not found:
            hook: dict = {}
            _configure_codex_hook(hook, event, invocation=invocation)
            group = {"hooks": [hook]}
            if event == "SessionStart":
                group["matcher"] = CODEX_SESSION_START_MATCHER
            groups.append(group)

    # Codex rejects hooks.json with a UTF-8 BOM on Windows, so always write its
    # config as plain UTF-8 even if a previous editor introduced a BOM.
    save_settings(path, settings, preserve_bom=False)
    print(f"Hooks do Codex registrados em {path}")
    if os.name == "nt":
        print(f"Wrapper do Codex registrado em {codex_wrapper_path()}")
    print("Abra `/hooks` no Codex e revise/confie nas novas definições antes de usá-las.")


def remove_codex_hooks(path: Path) -> None:
    settings = load_settings(path, "Codex")
    hooks = settings.get("hooks", {})
    if not isinstance(hooks, dict):
        return

    for event in CODEX_EVENTS:
        groups = hooks.get(event, [])
        if not isinstance(groups, list):
            continue
        remaining = []
        for group in groups:
            if not isinstance(group, dict):
                remaining.append(group)
                continue
            items = group.get("hooks", [])
            if not isinstance(items, list):
                remaining.append(group)
                continue
            kept = [
                item
                for item in items
                if not (isinstance(item, dict) and _our_codex_hook(item))
            ]
            if kept:
                remaining.append({**group, "hooks": kept})
        if remaining:
            hooks[event] = remaining
        else:
            hooks.pop(event, None)

    if not hooks:
        settings.pop("hooks", None)
    save_settings(path, settings, preserve_bom=False)

    if os.name == "nt":
        wrapper = codex_wrapper_path()
        if wrapper.exists():
            wrapper.unlink()

    print(f"Hooks do Codex removidos de {path}")


def demo_events() -> list[dict]:
    now = datetime.now(timezone.utc)

    def at(minutes: int) -> str:
        return (now + timedelta(minutes=minutes)).isoformat(timespec="seconds")

    return [
        {
            "id": "demo-01",
            "evento": EventName.SESSION_STARTED,
            "source": EventSource.CLAUDE_CODE,
            "session_id": "demo-atlas",
            "cwd": "/demo/atlas",
            "t": at(-12),
        },
        {
            "id": "demo-02",
            "evento": EventName.TURN_STARTED,
            "source": EventSource.CLAUDE_CODE,
            "session_id": "demo-atlas",
            "cwd": "/demo/atlas",
            "t": at(-11),
        },
        {
            "id": "demo-03",
            "evento": EventName.AGENT_STARTED,
            "source": EventSource.CLAUDE_CODE,
            "session_id": "demo-atlas",
            "agent_id": "demo-review",
            "agent_type": "reviewer",
            "cwd": "/demo/orion",
            "t": at(-8),
        },
        {
            "id": "demo-04",
            "evento": EventName.SESSION_STARTED,
            "source": EventSource.CLAUDE_CODE,
            "session_id": "demo-orion",
            "cwd": "/demo/orion",
            "t": at(-10),
        },
        {
            "id": "demo-05",
            "evento": EventName.TURN_FINISHED,
            "source": EventSource.CLAUDE_CODE,
            "session_id": "demo-orion",
            "cwd": "/demo/orion",
            "t": at(-2),
        },
        {
            "id": "demo-06",
            "evento": EventName.SESSION_STARTED,
            "source": EventSource.CLAUDE_CODE,
            "session_id": "demo-aurora",
            "cwd": "/demo/aurora",
            "t": at(-30),
        },
        {
            "id": "demo-07",
            "evento": EventName.AGENT_STARTED,
            "source": EventSource.CLAUDE_CODE,
            "session_id": "demo-aurora",
            "agent_id": "demo-index",
            "agent_type": "Explore",
            "cwd": "/demo/aurora",
            "t": at(-28),
        },
        {
            "id": "demo-08",
            "evento": EventName.SESSION_FINISHED,
            "source": EventSource.CLAUDE_CODE,
            "session_id": "demo-aurora",
            "cwd": "/demo/aurora",
            "reason": "other",
            "t": at(-20),
        },
    ]


def seed_demo(path: Path) -> None:
    path = path.expanduser().resolve()
    path.mkdir(parents=True, exist_ok=True)
    os.environ["AI_OPERATIONS_ROOM_DATA_DIR"] = str(path)
    from backend import projects
    from backend.db import connect, init_db

    init_db()
    with connect() as con:
        for table in ("evento", "execucao", "sessao"):
            con.execute(f"DELETE FROM {table} WHERE session_id LIKE 'demo-%'")
        con.execute("DELETE FROM ingestao WHERE chave IN ('events_offset', 'events_prefix')")
        if not projects.list_all(con):
            for name, folder in (
                ("Atlas CRM", "/demo/atlas"),
                ("Orion Flow", "/demo/orion"),
                ("Aurora Hub", "/demo/aurora"),
            ):
                projects.save(con, nome=name, caminho_local=folder)
    (path / "events.jsonl").write_text(
        "".join(json.dumps(event, ensure_ascii=False) + "\n" for event in demo_events()),
        encoding="utf-8",
    )
    (path / ".demo-mode").write_text("AI Operations Room demo\n", encoding="utf-8")
    print(f"Dados fictícios criados em {path}")


def serve(data_dir: str | None, port: int = 8765) -> None:
    if data_dir:
        os.environ["AI_OPERATIONS_ROOM_DATA_DIR"] = data_dir
    import uvicorn

    uvicorn.run("backend.api:app", host="127.0.0.1", port=port)


def main() -> int:
    parser = argparse.ArgumentParser(prog="ai-operations-room")
    commands = parser.add_subparsers(dest="action", required=True)

    for name in ("install", "remove"):
        item = commands.add_parser(f"hooks-{name}")
        item.add_argument("--settings", type=Path, default=settings_path())

    for name in ("install", "remove"):
        item = commands.add_parser(f"codex-hooks-{name}")
        item.add_argument("--settings", type=Path, default=codex_hooks_path())

    demo = commands.add_parser("demo")
    demo.add_argument(
        "--data-dir",
        type=Path,
        default=Path.home() / ".ai-operations-room-demo",
    )
    demo.add_argument("--serve", action="store_true")
    demo.add_argument("--port", type=int, default=8765)

    server = commands.add_parser("serve")
    server.add_argument("--data-dir")
    server.add_argument("--port", type=int, default=8765)

    args = parser.parse_args()
    if args.action == "hooks-install":
        install_hooks(args.settings)
    elif args.action == "hooks-remove":
        remove_hooks(args.settings)
    elif args.action == "codex-hooks-install":
        install_codex_hooks(args.settings)
    elif args.action == "codex-hooks-remove":
        remove_codex_hooks(args.settings)
    elif args.action == "demo":
        seed_demo(args.data_dir)
        if args.serve:
            serve(str(args.data_dir), args.port)
        else:
            print("Use `python -m backend.cli demo --serve` para abrir a demonstração.")
    else:
        serve(args.data_dir, args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
