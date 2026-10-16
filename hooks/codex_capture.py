"""Codex lifecycle hook: append metadata only, never conversation content."""

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

from backend.adapters.codex import normalize_codex_event


FIELDS = (
    "hook_event_name",
    "session_id",
    "cwd",
    "agent_id",
    "agent_type",
    "reason",
)

JSON_OUTPUT_EVENTS = {"Stop", "SubagentStop"}


def data_dir() -> Path:
    return Path(
        os.environ.get("AI_OPERATIONS_ROOM_DATA_DIR")
        or Path.home() / ".ai-operations-room"
    ).expanduser()


def prepare_payload(payload: dict) -> dict:
    event = {key: payload[key] for key in FIELDS if key in payload}

    # `source` in a Codex SessionStart payload describes how the session began;
    # it is not the Operations Room provider source.
    if (
        payload.get("hook_event_name") == "SessionStart"
        and isinstance(payload.get("source"), str)
    ):
        event["start_source"] = payload["source"]

    event["id"] = str(uuid.uuid4())
    event["t"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return event


def normalize(payload: dict) -> dict | None:
    return normalize_codex_event(prepare_payload(payload))


def main() -> int:
    source_event = None
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        if not isinstance(payload, dict):
            return 0

        source_event = payload.get("hook_event_name")
        if not payload.get("session_id"):
            return 0

        event = normalize(payload)
        if event is not None:
            path = data_dir()
            path.mkdir(parents=True, exist_ok=True)
            with (path / "events.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(event, ensure_ascii=False) + "\n")
    except Exception:
        # Observability must never break the Codex lifecycle.
        pass
    finally:
        # Codex Stop/SubagentStop command hooks expect JSON rather than plain text.
        # An empty object has no steering effect.
        if source_event in JSON_OUTPUT_EVENTS:
            sys.stdout.write("{}\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
