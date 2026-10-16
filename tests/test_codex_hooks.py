from __future__ import annotations

import json

from backend import cli
from backend.cli import install_codex_hooks, remove_codex_hooks


def test_codex_hook_registration_preserves_existing_hooks(tmp_path):
    settings = tmp_path / "hooks.json"
    settings.write_text(
        json.dumps(
            {
                "description": "keep me",
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
        ),
        encoding="utf-8-sig",
    )

    install_codex_hooks(settings)

    # Codex rejects a UTF-8 BOM in hooks.json, even if the previous editor
    # happened to write one.
    assert not settings.read_bytes().startswith(b"\xef\xbb\xbf")

    registered = json.loads(settings.read_text(encoding="utf-8"))

    assert registered["description"] == "keep me"
    assert len(registered["hooks"]["Stop"]) == 2
    assert registered["hooks"]["SessionStart"][-1]["matcher"] == "^(startup|resume|clear|fork)$"

    for event in (
        "SessionStart",
        "UserPromptSubmit",
        "SubagentStart",
        "SubagentStop",
        "Stop",
        "SessionEnd",
    ):
        assert event in registered["hooks"]

    remove_codex_hooks(settings)
    remaining = json.loads(settings.read_text(encoding="utf-8"))
    assert remaining == {
        "description": "keep me",
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


def test_codex_windows_command_uses_wrapper(tmp_path):
    wrapper = tmp_path / "codex-hook.cmd"
    command = cli.codex_command(
        windows=True,
        wrapper_path=wrapper,
    )

    assert command == f"cmd.exe /d /s /c {wrapper}"
    assert '"' not in command


def test_codex_wrapper_quotes_python_and_capture_script(
    tmp_path,
    monkeypatch,
):
    project = tmp_path / "Project With Spaces"
    wrapper = tmp_path / "codex-hook.cmd"
    python = tmp_path / "Python With Spaces" / "python.exe"

    monkeypatch.setattr(cli, "ROOT", project)
    monkeypatch.setattr(cli.sys, "executable", str(python))

    written = cli.write_codex_wrapper(wrapper)
    content = written.read_text(encoding="utf-8")

    assert written == wrapper
    assert content.startswith("@echo off\n")
    assert f'"{python}"' in content
    assert f'"{project / "hooks" / "codex_capture.py"}"' in content
    assert "exit /b %ERRORLEVEL%" in content


def test_wrapper_based_codex_hook_is_recognized():
    item = {
        "type": "command",
        "command": "cmd.exe /d /s /c C:/Users/test/.ai-operations-room/codex-hook.cmd",
        "commandWindows": "cmd.exe /d /s /c C:/Users/test/.ai-operations-room/codex-hook.cmd",
        "statusMessage": cli.CODEX_STATUS_MESSAGE,
    }

    assert cli._our_codex_hook(item)
