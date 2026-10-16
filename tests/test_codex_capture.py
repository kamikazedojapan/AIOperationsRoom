from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def run_hook(tmp_path: Path, payload: dict) -> subprocess.CompletedProcess[str]:
    hook = Path(__file__).resolve().parents[1] / "hooks" / "codex_capture.py"
    env = os.environ.copy()
    env["AI_OPERATIONS_ROOM_DATA_DIR"] = str(tmp_path)
    return subprocess.run(
        [sys.executable, str(hook)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        env=env,
        check=True,
    )


def test_codex_capture_discards_prompt_content(tmp_path: Path):
    result = run_hook(
        tmp_path,
        {
            "hook_event_name": "UserPromptSubmit",
            "session_id": "codex-1",
            "cwd": "/work",
            "turn_id": "turn-1",
            "prompt": "PRIVATE PROMPT",
        },
    )
    assert result.stdout == ""

    contents = (tmp_path / "events.jsonl").read_text(encoding="utf-8")
    assert "PRIVATE PROMPT" not in contents
    event = json.loads(contents)
    assert event["source"] == "codex"
    assert event["source_event"] == "UserPromptSubmit"
    assert event["evento"] == "turn.started"


def test_codex_stop_returns_neutral_json_and_discards_assistant_text(tmp_path: Path):
    result = run_hook(
        tmp_path,
        {
            "hook_event_name": "Stop",
            "session_id": "codex-1",
            "cwd": "/work",
            "turn_id": "turn-1",
            "last_assistant_message": "PRIVATE ANSWER",
            "stop_hook_active": False,
        },
    )
    assert json.loads(result.stdout) == {}

    contents = (tmp_path / "events.jsonl").read_text(encoding="utf-8")
    assert "PRIVATE ANSWER" not in contents
    event = json.loads(contents)
    assert event["evento"] == "turn.finished"
