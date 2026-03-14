# Architecture

ClawMonitor reads **local OpenClaw state** for real-time session observability, and optionally enriches it with **Gateway runtime** (channels snapshot) + **Gateway logs** via RPC.

The TUI is designed to stay responsive even when Gateway calls are slow:

- Refresh runs in a background thread.
- The main loop only renders cached snapshots and handles input.
- Expensive reads (JSONL tailing, logs tail) are cached with cheap change detectors (`sessions.json updatedAt`, cursor-based log tailing).

## Data sources

Offline (no Gateway required):

- Session index: `~/.openclaw/agents/*/sessions/sessions.json`
- Transcripts: `*.jsonl` referenced by session entries
- In-flight locks: `*.jsonl.lock` (pid + createdAt)
- Delivery failures: `~/.openclaw/delivery-queue/failed/**/*.json`
- Agent identity names: workspace `IDENTITY.md` (per agent)
  - Usually under `~/.openclaw/workspace*/IDENTITY.md`

Cron (local state):

- Cron jobs: `~/.openclaw/cron/jobs.json`
- Cron run status (best-effort): `~/.openclaw/cron/runs/<jobId>.jsonl`

Online (Gateway reachable):

- Gateway logs tail: `openclaw gateway call logs.tail --json` (incremental cursor)
- Channel runtime snapshot: `openclaw gateway call channels.status --json`

Telegram routing (local state):

- Thread bindings (conversation → sessionKey): `~/.openclaw/telegram/thread-bindings-<accountId>.json`

ACP sessions (local state, when enabled):

- ACPX sessions (ACP backend runtime): `~/.acpx/sessions/<acpxSessionId>.json`
  - Used to enrich ACP sessions that may not have a JSONL transcript file.

Optional user labels (configuration):

- Human-friendly labels for long ids (Feishu `ou_...`, Telegram chat ids, etc.) via `[labels]` in:
  - `~/.config/clawmonitor/config.toml`

## Outputs

- TUI: `clawmonitor tui` (tree view grouped by agent, color-coded rows, footer hotkeys, manual refresh and interval cycling)
- CLI status: `clawmonitor status --format text|json|md`
- CLI cron: `clawmonitor cron` (jobs + last run status)
- Export single-session report: `clawmonitor report --session-key ... --format json|md|both`
  - Written under `~/.local/state/clawmonitor/reports/` by default (XDG state dir)

## Security posture

- Never dumps `openclaw.json` to stdout or logs.
- Redacts token-like substrings in Gateway log lines and exported reports.
- Writes runtime logs and reports under XDG state dirs (`~/.local/state/clawmonitor/`), not inside the repo.
