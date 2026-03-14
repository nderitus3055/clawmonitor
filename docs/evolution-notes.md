# Evolution Notes (why it looks like this)

This is a lightweight record of the design/iteration logic, for future contributors.

## Observability framing

The core question isn’t “is the queue empty?” — it’s:

- What was the **last real inbound user message**, and when did it arrive?
- What was the **last outbound assistant message**, and when did it leave?
- Is the agent **working**, **finished**, **interrupted**, or did it **never receive** a real user message?

Everything else (logs, channel runtime, bindings) is supporting evidence.

## Key decisions

### Strict “Last User Send”

Transcripts can contain wrapper/system injections that look like `role=user`.
We treat “real inbound user text” strictly as `last_user_send` (wrapper-stripped), and track internal triggers separately as `last_trigger`.

### Long tasks without waiting for heartbeat

Heartbeat cadence can be 1 hour; tasks can finish in minutes.
We use lock files (`*.jsonl.lock`) and ACPX state as the source of truth for “still working”.

### Keep the TUI responsive

Gateway calls and JSONL tailing can stall.
Refresh runs in a background thread and renders cached snapshots, with caching for transcript tails and related logs.

### One filter toggle, not ten

Users quickly accumulate many sessions (main/heartbeat/channel/acp/subagent/cron/run records).
Rather than many toggles, we added a single Focus mode (`x`) that hides stale/boring sessions and keeps “interesting” ones.

### Human-friendly labels are local, editable, and shareable

Channel ids like Feishu `ou_...` are opaque without extra API calls.
We support a local `[labels]` map in `config.toml` and a TUI editor (`R`) that only rewrites the `[labels]` section.

## What we intentionally did not do (yet)

- Auto-fetch contact/group names from IM providers (would require API tokens/scopes and caching).
- A complex rules engine for filtering (Focus mode aims to be “good enough”).
