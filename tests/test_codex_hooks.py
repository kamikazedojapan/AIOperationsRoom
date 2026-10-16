from __future__ import annotations

import json

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
        encoding="utf-8",
    )

    install_codex_hooks(settings)
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
