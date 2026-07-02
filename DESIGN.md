# claude-usage-stats — Design

A lightweight, self-hosted dashboard that aggregates Claude Code transcript data
from an arbitrary number of machines and displays usage statistics at several
levels of granularity (time, session, project, branch, machine) with accurate
cost, plan-aware limits, and derived "highlights".

Primary use case: a personal, LAN-hosted tool aggregating ~4 machines' Claude
Code usage into one dashboard. Not aiming to be a polished OSS product — but
built to be *accurate* and genuinely differentiated from the crowd.

## Landscape (why this exists)

The space is crowded, but every popular tool is **single-machine** and stops at
token/cost time-series:

- **[ccusage](https://github.com/ccusage/ccusage)** (MIT) — de-facto standard CLI;
  daily/weekly/monthly/session reports. Sources pricing from **LiteLLM**. No
  cross-machine aggregation.
- **[phuryn/claude-usage](https://github.com/phuryn/claude-usage)** (MIT) — Python
  dashboard, clean `scanner.py` (parse → SQLite) / `dashboard.py` (server) split,
  incremental ingest. Single-machine ("each machine has its own `~/.claude`").
- Others: claude-code-stats, CCMeter, cctime (stuck-loop detection),
  claude-code-analytics (search + insights), a WebSocket real-time monitor.
- Official path: **[OpenTelemetry](https://code.claude.com/docs/en/agent-sdk/observability)**
  (`CLAUDE_CODE_ENABLE_TELEMETRY=1`) → Grafana/Datadog. There's an
  [open issue](https://github.com/anthropics/claude-code/issues/33978) asking
  Anthropic for a built-in `claude usage` command, so a first-party version may
  eventually land.

**Our whitespace:** central multi-machine aggregation + accurate plan-aware
limits + a derived-insight ("highlights") layer.

## Data sources

### Transcripts — `~/.claude/projects/**/*.jsonl`
One append-only JSONL file per session. Record `type` values observed:
`assistant`, `user`, `attachment`, `mode`, `last-prompt`, `permission-mode`,
`ai-title`, `file-history-snapshot`, `bridge-session`, `system`,
`queue-operation`, `started`, `result`, `custom-title`.

`assistant` records carry the usage we care about, per message:
- `message.usage`: `input_tokens`, `output_tokens`,
  `cache_creation_input_tokens`, `cache_read_input_tokens`, with
  `cache_creation.ephemeral_1h_input_tokens` / `ephemeral_5m_input_tokens`,
  `service_tier`, and `server_tool_use` (web search/fetch counts).
- Context on every record: `message.model`, `cwd`, `gitBranch`, `sessionId`,
  `isSidechain`, `version`, `uuid`, `parentUuid`, `timestamp`. `user` records
  also carry `permissionMode`, `promptSource`.

**Key gaps to remember:** transcripts contain **no `machine_id`** and **no
plan-limit percentages** — both are supplied at ingest/runtime, not in the file.

### Plan limits — statusline capture (not in transcripts)
Claude Code pipes a JSON blob to the statusline command at runtime containing the
**authoritative** subscription-window state:
`rate_limits.five_hour.{used_percentage,resets_at}` and
`rate_limits.seven_day.{used_percentage,resets_at}`, plus `cost.total_cost_usd`,
duration, and lines added/removed. Nothing persists it. We capture it by teeing
from the existing `claude-statusline.sh` on each machine into a log that gets
pulled and ingested.

> These windows are **per-Anthropic-account, not per-machine**. Snapshots from
> all 4 boxes describe the *same* account limit — merge into one account timeline
> (dedup on `resets_at` + `used_percentage`), **never sum across machines**.
> Statusline only fires during active sessions, so gaps between sessions are
> carried forward, not interpolated.

## Locked-in decisions

| # | Decision | Choice |
|---|----------|--------|
| 1 | Motivation | Personal daily-driver; accurate and differentiated, not a productized OSS release. |
| 2 | Build strategy | **Borrow, don't fork.** Seed the parser from phuryn's `scanner.py` (MIT, attributed); consume LiteLLM's price file the way ccusage does; build the web layer fresh. |
| 3 | Architecture | **Central aggregation.** One central host runs one SQLite DB + dashboard; it pulls from the other machines. Host-agnostic (config-driven source list); pick the central box at deploy time. |
| 4 | Multi-machine transport | **Central pull** over ssh/rsync (WireGuard optional, plain SSH on LAN). Plus a later **manual import wizard** for tarballs from external machines — same dedup path. |
| 5 | Machine identity | Assigned at the ingest boundary. Pull → `machine_id = source hostname`. Import → wizard label. Drop a `machine-id` marker into a machine's `~/.claude` on first contact so re-imports merge, not duplicate. |
| 6 | Ingest semantics | **Idempotent, keyed on record `uuid`** (re-scan/re-pull/re-import never double-counts). Incremental via per-file byte offset (JSONL append-only within a session). |
| 7 | Cost model | **Both / plan-aware.** API-equivalent value from token breakdown × **LiteLLM** per-model rates (separate input/output/cache-write/cache-read), *plus* plan-usage vs limits. Offline price fallback baked into the image. |
| 8 | Plan-limit accuracy | **Accurate.** Tee `rate_limits` snapshots from `claude-statusline.sh` on all machines into a log the dashboard ingests → real 5h/7d curves. (Snippet handed to the user to wire in; not auto-installed.) |
| 9 | Tech stack | **FastAPI + Jinja2 + htmx + SQLite.** |
| 10 | Deployment | **Docker Compose from the start**, portable across candidate central hosts. |
| 11 | Compose topology | **Dedicated `worker` container** (ssh/rsync + scheduler, **sole DB writer**, mounts restricted read-only deploy key) + **`web`** container (uvicorn, opens DB **read-only**, serves LAN port) + named volumes (`db`, `staging`, `config`). SQLite stays happy: single writer. |
| 12 | Scope | Nail Claude Code transcripts first. Keep the event schema source-agnostic so other sources bolt on later — but don't build the generic version until a second source is in hand. |

## Architecture (v1)

```
 machine-1  machine-2  machine-3  machine-4     (each: ~/.claude/projects + statusline rate-limit log)
     \          |          |          /
      \         |          |         /   ssh/rsync (read-only deploy key)
       v        v          v        v
   ┌─────────────────────── central host ───────────────────────┐
   │  docker compose                                             │
   │                                                             │
   │   worker  ──(pull → staging vol)──> ingest ──(write)──┐     │
   │     └ scheduler, sole DB writer                       │     │
   │                                                    ┌──v──┐  │
   │                                            db vol  │SQLite│ │
   │                                                    └──^──┘  │
   │   web  ──(read-only)──────────────────────────────────┘    │
   │     └ FastAPI/uvicorn + Jinja2/htmx  →  LAN port            │
   └─────────────────────────────────────────────────────────────┘
```

## Metric definitions & sources (canonical, July 2026)

Grounded in Anthropic's current docs so our numbers match what Claude Code shows
users — not assumptions.

### Per-model API pricing (USD per 1M tokens; base input / output)

Source: `claude-api` skill model table (cached 2026-06-24) + LiteLLM at build.

| Model | Input | Output |
|---|---|---|
| `claude-opus-4-8` / `4-7` / `4-6` | $5 | $25 |
| `claude-sonnet-5` | $3 ($2 intro through 2026-08-31) | $15 ($10 intro) |
| `claude-sonnet-4-6` | $3 | $15 |
| `claude-haiku-4-5` | $1 | $5 |
| `claude-fable-5` | $10 | $50 |

Our corpus is ~99% `claude-opus-4-8`. **Don't hardcode** — consume LiteLLM's
`model_prices_and_context_window.json` (baked into the image + periodic refresh)
so new models/price changes flow in automatically. The table above is the
sanity-check baseline and offline fallback.

### Prompt-cache multipliers (× base input rate)

Source: `claude-api` skill `shared/prompt-caching.md` § Economics.

| Token class | Multiplier | Transcript field |
|---|---|---|
| Cache **read** | **0.1×** | `cache_read_input_tokens` |
| Cache **write, 5-min TTL** | **1.25×** | `cache_creation.ephemeral_5m_input_tokens` |
| Cache **write, 1-hour TTL** | **2.0×** | `cache_creation.ephemeral_1h_input_tokens` |

### Per-message cost formula

`cache_creation_input_tokens` is the **total** of the two ephemeral buckets
(verified in-corpus: a record with `cache_creation_input_tokens=2595` had
`ephemeral_1h=2595, ephemeral_5m=0`). Price from the ephemeral breakdown, not the
total, so 5m vs 1h TTLs get their correct multiplier — never double-count.

```
cost = input_tokens              × R_in
     + output_tokens             × R_out
     + ephemeral_5m_input_tokens × R_in × 1.25
     + ephemeral_1h_input_tokens × R_in × 2.0
     + cache_read_input_tokens   × R_in × 0.10
```

Plus `server_tool_use.web_search_requests` / `web_fetch_requests` as a separate
per-request line (minor; price from LiteLLM). Unknown model → cost `null` +
logged, never guessed.

### Plan-aware limits (subscription windows)

Source: `code.claude.com/docs/en/costs` (`/usage`) + the statusline JSON schema.
- Windows are **`five_hour`** and **`seven_day`** rolling, **per-Anthropic-account**.
- Authoritative `used_percentage` + `resets_at` are only piped to the statusline
  command live (`rate_limits.five_hour` / `.seven_day`) — hence the tee capture.
- **Validates our whitespace:** Anthropic's own `/usage` is explicitly
  *"computed from local session history on this machine … usage from other
  devices or claude.ai is not included."* Our central aggregation is exactly
  what their first-party tool doesn't do.

### Official metric vocabulary (align our schema names to these)

Source: `code.claude.com/docs/en/monitoring-usage` (OpenTelemetry).
- `claude_code.token.usage` — attr `type` ∈ {`input`,`output`,`cacheRead`,`cacheCreation`}.
- `claude_code.cost.usage` (USD), `claude_code.session.count`,
  `claude_code.lines_of_code.count`, `claude_code.active_time.total`.
- We ingest transcripts (richer per-message detail), but we mirror this
  vocabulary so the dashboard reads familiarly and an optional OTEL source can
  bolt on later without schema churn.

## Data model (sketch — finalized in the v1 plan)

- **events** — one row per transcript record we value (PK `uuid`, `machine_id`,
  `session_id`, `ts`, `model`, `cwd`, `git_branch`, `is_sidechain`, token
  columns, `service_tier`, `web_search`/`web_fetch`, computed `cost_usd`).
- **sessions** — derived rollup per `session_id` (machine, project, first/last
  ts, totals, title).
- **account_timeline** — rate-limit snapshots (`ts`, `window` ∈ {5h,7d},
  `used_percentage`, `resets_at`), one account, deduped.
- **prices** — LiteLLM per-model rate cache (refresh + offline fallback).
- **machines** — `machine_id`, hostname, label, source config.
- **ingest_state** — per-file byte offset + mtime for incremental scans.

## Derived "highlights" (differentiators)

Cost per project (`cwd`) / per git branch; cache-efficiency (`cache_read`
savings); per-machine breakdown; most-expensive sessions & prompts; tool-use
mix; subagent fan-out (`isSidechain`); web-search spend; time-of-day patterns.

## Explicitly deferred

Import wizard (external tarballs), non-Claude-Code sources, OTEL ingestion,
auth/multi-user. Schema stays source-agnostic to keep these cheap later.
