# Token Monitor Research and TUI Column Strategy

Checked on: 2026-03-19

This note captures the current research for adding token visibility to ClawMonitor.
It combines:

- external repo review
- upstream OpenClaw capability review
- local runtime data validation
- TUI interaction recommendations

The goal is to answer 4 questions:

1. Does OpenClaw already record token usage per session?
2. Can ClawMonitor show token usage in both the right panel and the main list?
3. Can the TUI support a "freeze left columns, move right columns" table model?
4. Can token views support `1d / 7d / 30d` ranges?

## Short answer

Yes, token monitoring is worth adding, and the data source already exists.

The right implementation order is:

1. `sessions.json` current snapshot for immediate per-session token visibility
2. Gateway `sessions.usage` / `sessions.usage.timeseries` for real range-based views
3. file size or transcript-derived estimates only as a last-resort fallback

For the TUI, the best fit is not true pixel-smooth horizontal scrolling. It is a frozen-left-column table with a logical horizontal column window that moves by column groups.

## External repos: what is worth learning

### `ai7eam-dev/openclaw-watchdog`

Repo: <https://github.com/ai7eam-dev/openclaw-watchdog>

Most useful idea:

- Separate "health detection" from "session browsing".

What to borrow:

- explicit watchdog-style state classes
- remediation-oriented language
- focus on stale / blocked / degraded states, not only "is the process alive"

What not to copy directly:

- this style is stronger on recovery and service health than on dense session inspection
- it is not the best primary UI model for a keyboard-heavy session monitor

### `EvanDataForge/openclaw-sessionwatcher`

Repo: <https://github.com/EvanDataForge/openclaw-sessionwatcher>

Most useful idea:

- drill into a selected session only when the user asks for detail

What to borrow:

- explicit refresh instead of over-eager background loading
- session detail as a second-stage action
- keeping monitoring and deep inspection separate

Why it matches ClawMonitor:

- ClawMonitor is already moving in this direction with explicit history loading
- the same pattern is a good fit for usage/token detail loading

### `DanWahlin/claw-monitor`

Repo: <https://github.com/DanWahlin/claw-monitor>

Most useful idea:

- operator-first information architecture

What to borrow:

- summary-first layout
- selected-row detail on the side
- strong keyboard-first navigation

Why it matters:

- token data should become part of operator visibility, not a hidden diagnostic screen

## Upstream OpenClaw: relevant existing capabilities

OpenClaw already treats usage tracking as a first-class feature:

- `README.md` documents usage tracking as part of runtime behavior.
- `CHANGELOG.md` includes a Web UI token usage dashboard.
- Gateway methods exist for usage summaries and per-session details.

Relevant upstream references:

- `/home/qagent/projects/openclaw/README.md`
- `/home/qagent/projects/openclaw/CHANGELOG.md`
- `/home/qagent/projects/openclaw/ui/src/ui/controllers/usage.ts`
- `/home/qagent/projects/openclaw/src/gateway/server-methods/usage.ts`
- `/home/qagent/projects/openclaw/src/agents/usage.ts`

Key gateway methods already present upstream:

- `sessions.usage`
- `sessions.usage.timeseries`
- `sessions.usage.logs`
- `usage.cost`

This is important because `1d / 7d / 30d` is not something ClawMonitor can derive correctly from a single session snapshot alone.

## Local runtime validation

ClawMonitor's local OpenClaw state already contains per-session token fields in:

- `~/.openclaw/agents/*/sessions/sessions.json`

Observed fields in the current machine state:

- `inputTokens`
- `outputTokens`
- `totalTokens`
- `contextTokens`
- `totalTokensFresh`
- `cacheRead`
- `cacheWrite`
- `modelProvider`
- `model`

Examples from the current machine:

- `agent:main:telegram:default:direct:8561029144`
  - `inputTokens=433627`
  - `outputTokens=3347`
  - `totalTokens=110336`
  - `contextTokens=400000`
- `agent:main:heartbeat`
  - `inputTokens=65697`
  - `outputTokens=2912`
  - `totalTokens=73922`
  - `contextTokens=204800`
  - `cacheRead=73895`
- `agent:main:feishu:group:oc_7de2e8a4729f23393f43424ca556146a`
  - `inputTokens=260890`
  - `outputTokens=1836`
  - `totalTokens=40857`
  - `contextTokens=400000`

Conclusion:

- ClawMonitor does not need to start from transcript size estimation.
- There is already enough local data for a useful first version.

## A critical semantic detail

Do not treat `totalTokens` as "all tokens spent".

Upstream OpenClaw explicitly documents that session `totalTokens` is used as a prompt/context snapshot and intentionally excludes completion/output tokens.

Implication:

- `inputTokens`, `outputTokens`, `cacheRead`, `cacheWrite` are the "consumption" metrics
- `totalTokens` and `contextTokens` are better used as "context pressure" metrics

Recommended display model:

- Consumption:
  - input
  - output
  - cache read
  - cache write
- Pressure:
  - prompt/context used
  - context limit
  - percent used

This avoids misleading users with a single overloaded "tokens" number.

## Recommended ClawMonitor token model

### Level 1: current snapshot from local session state

Data source:

- `sessions.json`

Good for:

- right-side selected session details
- list sorting/ranking by current usage
- context pressure display
- offline mode

Not enough for:

- true `1d / 7d / 30d` usage windows
- historical trend charts

### Level 2: range-based usage from Gateway

Data source:

- `sessions.usage`
- `sessions.usage.timeseries`
- `sessions.usage.logs`

Good for:

- `1d / 7d / 30d` session usage summaries
- per-agent aggregation in a selected time range
- top-burner ranking
- usage trends

Tradeoff:

- this should be user-triggered or cached
- loading may be slow depending on gateway and date range

### Level 3: estimate fallback

Fallback only when usage is unavailable:

- session JSONL file size
- transcript message count
- derived activity count

Rules:

- label estimates clearly as estimates
- never mix them visually with real token data without an `EST` label

## Where token data should appear

### Right panel

Yes, this is required.

Recommended block:

- `TOKEN`
- `provider/model`
- `input / output / cacheR / cacheW`
- `contextUsed / contextLimit / pct`
- `fresh / stale`
- if Gateway range mode is active: `range=1d|7d|30d`

This is the lowest-risk addition and should land first.

### Main list

Yes, also worth doing.

Reason:

- token-heavy sessions are often the sessions that deserve operator attention
- large-context sessions are easy to miss if token data exists only in the detail pane

But the list should stay readable. That means token columns must be controlled, not always fully expanded.

## Can the TUI do "freeze first column, horizontally move the rest"?

Yes, in a terminal-friendly form.

### What is realistic in curses

Curses can redraw the table on each key press and maintain a logical horizontal offset.

So the TUI can support:

- frozen left columns
- right-side column groups that change when pressing left/right
- instant redraw that feels smooth enough in a terminal

What it cannot do well:

- real pixel-smooth scrolling like a GUI spreadsheet
- inertia-style horizontal animation

### Recommended model

Freeze the identity columns:

- `NODE`
- `STATE`

Optionally freeze one more narrow column:

- `FLAGS`

Then let the metric columns slide in groups.

Proposed horizontal column pages:

1. Activity page
   - `USER`
   - `ASST`
   - `RUN`
   - `FLAGS`
   - `SESSION`

2. Token current page
   - `IN`
   - `OUT`
   - `CACHE`
   - `CTX`
   - `SESSION`

3. Token range page
   - `1D`
   - `7D`
   - `30D`
   - `AVG`
   - `SESSION`

4. History/ops page
   - `HIST`
   - `ERR`
   - `MODEL`
   - `SESSION`

### Why page-by-column-group is better than char-by-char scrolling

- easier to understand
- better footer/help text
- avoids ugly partial columns
- easier to keep width calculations deterministic
- better for narrow terminals

### Suggested keys

- `Left/Right`: previous/next column page
- footer/header should show the current page explicitly
  - example: `Cols=activity`
  - example: `Cols=tokens-current`
- `z` can remain pane-layout switching; do not overload it with horizontal table movement

## Can token stats support `1d / 7d / 30d`?

Yes, but only if the source is historical usage data, not just current session metadata.

### What local `sessions.json` can do

It can show only the latest known snapshot:

- current input/output/cache/context
- current context pressure

It cannot answer:

- how many tokens this session used in the last day
- how much was spent in the last 7 days
- what changed over the last 30 days

### What is needed for true range views

One of these:

1. Gateway usage APIs
   - preferred
2. locally cached periodic usage snapshots
   - acceptable fallback for offline mode
3. transcript re-scan plus usage extraction
   - possible, but heavier and less reliable than upstream usage APIs

### Recommended range design

Use:

- `1d`
- `7d`
- `30d`

And make the meaning explicit:

- session range mode if a session is selected
- agent aggregate range mode if the list is grouped by agent

### Refresh behavior

Do not auto-refresh long-range usage aggressively.

Recommended:

- manual trigger for initial load
- cache results per `(scope, range, date)`
- mark stale visually
- allow user refresh with `r`

## Recommended implementation order

### Phase 1

- Add token block to the right status/detail pane using local `sessions.json`
- Add compact current token columns to the list
- No date-range logic yet

### Phase 2

- Add column pages with frozen left columns
- Add a token-focused list page
- Add clear footer state for current column page

### Phase 3

- Integrate Gateway `sessions.usage`
- Add `1d / 7d / 30d` mode for selected session and agent aggregates
- Cache results and show loading/stale states

### Phase 4

- Add ranking and sorting
  - top token consumers
  - highest context pressure
  - highest cache-read ratio

## Final recommendation

The feature is worth doing.

The safest product shape is:

- right pane token block first
- main-list token columns second
- range views third

And for the TUI interaction model:

- use frozen identity columns
- use left/right to switch metric column pages
- do not attempt GUI-style smooth scrolling

That model matches terminal constraints, keeps the list readable, and leaves room for `1d / 7d / 30d` token views later.
