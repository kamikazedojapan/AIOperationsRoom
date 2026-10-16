from __future__ import annotations

def session_key(
    source: str,
    session_id: str,
) -> str:
    return f"{source}:{session_id}"

def main_execution_key(
    source: str,
    session_id: str,
) -> str:
    return (
        f"{session_key(source, session_id)}"
        ":main"
    )

def agent_execution_key(
    source: str,
    session_id: str,
    agent_id: str,
) -> str:
    return (
        f"{session_key(source, session_id)}"
        f":agent:{agent_id}"
    )