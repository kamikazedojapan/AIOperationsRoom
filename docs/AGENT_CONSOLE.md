# Agent Console / Task Runner

Agent Console starts work explicitly requested by the user and tracks that task separately from global Operations Room telemetry.

## Privacy boundary

The existing hook/event pipeline remains metadata-only. It must not begin capturing prompts or assistant responses from external Claude, Codex, OpenAI, or ChatGPT sessions.

Content entered directly into Agent Console is different: it is task-owned data. The local `task` table may store the prompt, selected model and final output because the user explicitly submitted the task through this surface. Task lifecycle events are persisted in `task_event` for the console timeline.

## Task contract

Statuses:

- `queued`
- `running`
- `waiting`
- `completed`
- `failed`
- `cancelled`

Task records store `id`, `source`, `agent`, optional `project_id`, optional `model`, prompt, status, provider session ID, final output/error, cancellation flag and timestamps. `task_event` is an append-only timeline used by the UI.

Tasks finalizadas may be deleted through the Agent Console. Their timeline is removed by the database `ON DELETE CASCADE`. Active tasks must be cancelled or completed first.

## Provider interface

`backend.task_runner` owns provider-neutral scheduling and persistence. Providers implement availability plus a `run(task, emit, is_cancelled)` operation. Provider-specific SDK/CLI calls do not belong in API endpoints or `runs.py`.

The v0.8.0 registry includes:

- `codex` — local Codex CLI task provider;
- `ollama` — local Ollama task provider;
- `openai_api` — OpenAI Agents API provider.

The provider catalog exposes availability, reason for unavailability, capabilities and available models when applicable. The UI uses this metadata instead of hard-coding provider-specific behavior.

## Codex Local

`CodexTaskProvider` executes bounded tasks through `codex exec --json` and inherits the user's local Codex authentication.

When a project is selected, its local path becomes the process `cwd`. The provider detects supported unattended/workspace-write flags from `codex exec --help` to remain compatible with current and legacy CLI versions.

Cancellation is cooperative from the Agent Console and forcefully stops the local process tree when necessary on Windows.

## Ollama Local

`OllamaTaskProvider` discovers the local service through `/api/tags`, exposes installed models and runs tasks through streaming `/api/chat`.

The selected model is persisted with the task. `AI_OPERATIONS_ROOM_OLLAMA_MODEL` can be used as a fallback preference, and `AI_OPERATIONS_ROOM_OLLAMA_URL` or `OLLAMA_HOST` can override the local endpoint.

When a project is selected, Ollama receives the project name and CWD as explicit context metadata only. It does not receive implicit filesystem access, and the system prompt instructs the model not to claim it has read files unless their contents were explicitly supplied.

For Qwen3, the provider also filters accidental reasoning text from task output when the model emits a `</think>` boundary despite `think=false`.

## Progress and cancellation

The UI polls `/api/tasks/{task_id}/events` roughly once per second. The event contract is cursor-based so SSE or WebSocket can replace polling later without changing task semantics.

Codex and Ollama keep cancellation responsive even while their native stdout/HTTP streams are waiting for new data. The provider runner checks the persisted cancellation request independently of stream arrival.

## Persistence and restart recovery

Task history, selected model, final output and timeline are stored in SQLite.

On server startup, non-final tasks that cannot be resumed are recovered into a terminal state: tasks with a pending cancellation become `cancelled`; other interrupted tasks become `failed`. This prevents stale `running` tasks from remaining permanently undeletable after a restart.

## OpenAI session lifetime

OpenAI Agent tasks are one-shot. After a completed/cancelled task, the provider attempts to delete the managed OpenAI Agent session unless `AI_OPERATIONS_ROOM_KEEP_OPENAI_SESSIONS=1` is set.

The selected local project is metadata only for the OpenAI-hosted integration. The local directory is not uploaded or mounted into the hosted sandbox.

## Project behavior by provider

- **Codex Local:** selected project path becomes the real local `cwd`.
- **Ollama Local:** project name and CWD are supplied as metadata/context, without implicit file access.
- **OpenAI Agents API:** project remains local metadata; files are not transferred automatically.

This distinction preserves the project's privacy boundary while still allowing local providers to use the appropriate execution context.
