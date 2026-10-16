# OpenAI integration strategy

Stage 6 uses the **OpenAI Agents API** as the first OpenAI surface integrated into AI Operations Room.

Why this surface:

- it exposes durable sessions and turns instead of requiring us to infer lifecycle from text generation;
- it provides an official live event stream;
- it exposes subagent lifecycle events;
- it supports OpenAI-hosted execution environments;
- it can later back the Agent Console without coupling the core state machine to OpenAI-specific names.

The ordinary ChatGPT product is **not** treated as an observable runtime. AI Operations Room does not assume access to private ChatGPT conversation lifecycle events.

## Provider mapping

| OpenAI Agents event | Internal fact |
| --- | --- |
| `agent.session.created` | `session.started` |
| `agent.session.turn.in_progress` | `turn.started` |
| `agent.session.subagent.created` | `agent.started` |
| `agent.session.subagent.active` | `agent.started` |
| `agent.session.subagent.closed` | `agent.finished` |
| `agent.session.turn.completed` | `turn.finished` |

Output text deltas, reasoning text and other content events are not written into global Operations Room telemetry. Content intentionally submitted through Agent Console belongs to that task only.

Failure/cancellation events are handled by the Task Runner status model. They are not currently projected into the global event contract because that contract does not yet define provider-neutral failure/cancellation facts.

## Runtime requirements

A real Agent Console execution requires `OPENAI_API_KEY` with the permissions required by the Agents API. The OpenAI Python SDK adds the Agents beta header automatically.

The default model is configurable through `AI_OPERATIONS_ROOM_OPENAI_MODEL`; the Task Runner provides the actual default.
