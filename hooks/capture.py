"""Claude Code hook: append metadata only, never conversation content."""

from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from backend.adapters.claude import normalize_claude_event


FIELDS = (
    "hook_event_name",
    "session_id",
    "cwd",
    "agent_id",
    "agent_type",
    "reason",
)

BACKGROUND_FIELDS = (
    "id",
    "type",
    "status",
    "agent_type",
)


def data_dir() -> Path:
    return Path(
        os.environ.get("AI_OPERATIONS_ROOM_DATA_DIR")
        or Path.home() / ".ai-operations-room"
    ).expanduser()


def prepare_payload(payload: dict) -> dict:
    event = {
        key: payload[key]
        for key in FIELDS
        if key in payload
    }

    event["id"] = str(uuid.uuid4())
    event["t"] = datetime.now(
        timezone.utc
    ).isoformat(timespec="seconds")

    tasks = payload.get("background_tasks")

    if isinstance(tasks, list):
        event["background_tasks"] = [
            {
                key: task[key]
                for key in BACKGROUND_FIELDS
                if key in task
            }
            for task in tasks
            if isinstance(task, dict)
        ]

    return event


def normalize(payload: dict) -> dict:
    prepared = prepare_payload(payload)

    return normalize_claude_event(prepared)


def main() -> int:
    try:
        payload = json.loads(
            sys.stdin.read() or "{}"
        )

        if (
            not isinstance(payload, dict)
            or not payload.get("session_id")
        ):
            return 0

        path = data_dir()
        path.mkdir(
            parents=True,
            exist_ok=True,
        )

        event = normalize(payload)

        with (
            path / "events.jsonl"
        ).open(
            "a",
            encoding="utf-8",
        ) as stream:
            stream.write(
                json.dumps(
                    event,
                    ensure_ascii=False,
                )
                + "\n"
            )

    except Exception:
        pass

    return 0


if __name__ == "__main__":
    sys.exit(main())