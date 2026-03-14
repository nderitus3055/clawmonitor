# Status model

Per session, ClawMonitor tracks:

- **last_user**: newest transcript message with `role=user` (may include internal wrapper/control-plane injections)
- **last_user_send**: best-effort “real inbound” user message extracted from common wrapper formats (preview + timestamp)
- **last_trigger**: newest internal/control-plane trigger message (if present)
- **last_assistant**: last transcript message with `role=assistant` (preview + timestamp, stopReason)
- **lock**: `sessionFile + ".lock"` (pid + createdAt) → indicates active run and run duration
- **acpx (ACP sessions)**: when `sessions.json` has `acp.identity.acpxSessionId`, ClawMonitor may read `~/.acpx/sessions/<id>.json` to tail ACP messages and detect ACP runs even without JSONL locks
- **abortedLastRun**: from `sessions.json`
- **delivery failure**: from `delivery-queue/failed` entries keyed by `mirror.sessionKey`
- **channel IO** (optional): `channels.status` lastInboundAt/lastOutboundAt for the channel account (Gateway online)
- **cron job (optional)**: if the session key matches `agent:<agentId>:cron:<jobId>...`, ClawMonitor can map it to a job name via `~/.openclaw/cron/jobs.json`
- **identity name (optional)**: agent display name from workspace `IDENTITY.md` (shown as `name(agentId)`)

## Primary states

- `WORKING`: lock file exists, or an ACP session reports `acp.state in (running,pending)` (best-effort; may be enriched via ACPX)
- `FINISHED`: no lock; last_assistant timestamp is >= last_user timestamp (when last_user exists)
- `INTERRUPTED`: no lock; `abortedLastRun=true` and last_user is newer than last_assistant
- `NO_MESSAGE`: no user message exists in transcript

## Alerts (orthogonal)

- `NO_FEEDBACK`: no lock but last_user is newer than last_assistant (the “queue empty but no reply” problem)
- `LONG_RUN`: lock exists and duration exceeds thresholds (default warn 15m, critical 60m)
- `DELIVERY_FAILED`: there is a failed delivery record for the session key
- `SAFETY`: last assistant stopReason hints safety/refusal/content_filter (heuristic)
- `SAFEGUARD_OFF`: agent compaction mode is not `safeguard` (best-effort snapshot from `openclaw.json`)
- `TRXM`: transcript missing (sessionFile exists but referenced `*.jsonl` is missing)
- `BOUND_OTHER` / `BIND`: Telegram chat is routed to another session key via thread bindings

## UI-only features

These do not change the underlying state computation, but help when you have dozens of sessions:

- **Focus filter** (TUI key `x`): hides stale sessions and keeps “interesting” ones:
  - working / interrupted / pending reply
  - delivery failures, safety/safeguard issues, stale locks, transcript missing
  - explicitly labeled sessions
  - recently active sessions (last N hours)
- **Labels** (TUI key `R`): write a human-friendly label into config `[labels]` so `ou_...` style ids become readable.
