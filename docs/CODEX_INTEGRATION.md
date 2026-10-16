# Codex integration

The Operations Room observes local Codex sessions through the official Codex lifecycle hooks framework.

Official references:

- https://developers.openai.com/codex/hooks
- https://developers.openai.com/codex/config-reference
- https://github.com/openai/codex/blob/main/docs/config.md

## Why lifecycle hooks

Codex officially supports command hooks during the agentic lifecycle. Hook configuration can live in `~/.codex/hooks.json`, `~/.codex/config.toml`, or their project-local equivalents. Non-managed hooks must be reviewed and trusted in Codex with `/hooks` before they run.

Hooks are enabled by default in current Codex releases. The legacy `codex_hooks` feature key is a deprecated alias for `hooks`.

## Mapping

| Codex lifecycle hook | Operations Room fact | Notes |
| --- | --- | --- |
| `SessionStart` | `session.started` | Captured for startup/resume/clear/fork. `source=compact` is intentionally ignored because compaction can happen mid-turn and is not a new session fact. |
| `UserPromptSubmit` | `turn.started` | Prompt text is deliberately discarded. |
| `SubagentStart` | `agent.started` | Uses Codex `agent_id` and `agent_type`. |
| `SubagentStop` | `agent.finished` | Assistant/subagent message content is deliberately discarded. |
| `Stop` | `turn.finished` | Latest assistant message is deliberately discarded. |
| `SessionEnd` | `session.finished` | Current Codex end reason is `other`. |

Other hooks such as tool use, compaction, permission requests, and interrupt are not mapped because the current provider-neutral contract has no equivalent fact for them.

## Privacy boundary

Codex exposes prompt text to `UserPromptSubmit` and assistant text to stop hooks. `hooks/codex_capture.py` does not persist either field. The global telemetry stream remains metadata-only, matching the Claude integration.

## Install

```powershell
uv run python -m backend.cli codex-hooks-install
```

The installer merges its command hooks into `~/.codex/hooks.json` and preserves unrelated user hooks. It also rewrites the file as UTF-8 without a BOM because current Codex Windows builds reject a BOM in `hooks.json`.

On Windows, the installer writes a small shim at `~/.ai-operations-room/codex-hook.cmd`. Codex invokes the shim through an unquoted `cmd.exe /d /s /c ...` command, while the shim itself safely quotes the Python executable and `hooks/codex_capture.py`. This avoids the current Windows hook-parser failure seen when the hook command directly contains quoted executable paths with spaces.

After installation, start Codex and use `/hooks` to review and trust the new definitions.

Remove only the Operations Room hooks with:

```powershell
uv run python -m backend.cli codex-hooks-remove
```

The remove command also deletes the Windows shim created by the installer.

## Functional validation

A real Codex CLI session was validated on Windows with trusted hooks: `SessionStart`, `UserPromptSubmit`, and stop lifecycle callbacks reached the Operations Room without `Hook failed`, and the session appeared under provider `codex` in the dashboard.

Automated tests continue to cover normalization, privacy filtering, hook-file merging, provider isolation, UTF-8/BOM behavior, and the Windows shim command.
