# Agent Console / Task Runner

Agent Console starts work explicitly requested by the user and tracks that task separately from global Operations Room telemetry.

## Privacy boundary

The existing hook/event pipeline remains metadata-only. It must not begin capturing prompts or assistant responses from external Claude, Codex, OpenAI, or ChatGPT sessions.

Content entered directly into Agent Console is different: it is task-owned data. The local `task` table may store the prompt and final output because the user explicitly submitted the task through this surface. Provider lifecycle events copied to `events.jsonl` contain operational metadata only.

## Task contract

Statuses:

- `queued`
- `running`
- `waiting`
- `completed`
- `failed`
- `cancelled`

Task records store `id`, `source`, `agent`, optional `project_id`, prompt, status, provider session ID, final output/error, cancellation flag and timestamps. `task_event` is an append-only timeline used by the UI.

## Provider interface

`backend.task_runner` owns provider-neutral scheduling and persistence. Providers implement availability plus a `run(task, emit, is_cancelled)` operation. Provider-specific SDK calls do not belong in API endpoints or `runs.py`.

The first provider is `openai_api`, implemented with the OpenAI Agents API and an OpenAI-hosted sandbox.

## Progress delivery

The first UI version uses one-second polling against `/api/tasks/{task_id}/events`. This keeps the implementation simple and local. The event contract is cursor-based so SSE or WebSocket transport can replace polling later without changing task semantics.

## OpenAI session lifetime

Agent Console currently treats each task as one-shot. After a completed/cancelled task, the provider deletes the managed OpenAI Agent session and records `session.finished` from that real cleanup action. Set `AI_OPERATIONS_ROOM_KEEP_OPENAI_SESSIONS=1` to retain managed sessions for debugging or a future multi-turn console.

## Project selector limitation

Selecting a local project currently associates metadata with the task. It does **not** upload, mount, or expose that local directory to the OpenAI-hosted sandbox. Project file transfer or a self-hosted environment must be designed explicitly before local source code is made available to the remote agent.
