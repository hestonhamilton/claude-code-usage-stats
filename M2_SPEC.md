# M2 SPEC — "Value Realized" metric

> Untracked scratch spec for the next implementer (Codex primary, or a Sonnet
> subagent if Codex is rate-limited). Architect/reviewer = Claude: delegate,
> then **reconcile the result against raw data** — do not trust the
> implementer's own tests.
>
> Branch off `v2-m1` (which holds committed M1). Milestone context and the v2
> decisions live in `HANDOFF.md` and project memory.

## Objective
Add a **"value realized"** view answering *"am I getting my money's worth from
the subscription?"* — framed so that **100% of a plan usage-limit reached = 100%
value extracted.** The existing **API-equivalent value ($) stays the headline**;
value-realized is a *second-tier* companion, not a replacement.

There are two metrics. **A** is the user's stated framing (plan utilization). **B**
is a companion that needs no new capture and is the most immediately compelling —
build both.

---

## Ground-truth data facts (verified 2026-07-02)
- **Single shared Max5 account across all 4 machines** → ONE 5h window and ONE 7d
  window. Rate-limits are account-global, so a snapshot from *any* machine
  describes the same window; merging all machines' snapshots into one timeline is
  correct. `ingest_ratelimits_file` already dedups via
  `INSERT OR IGNORE` on the `account_timeline` PK `(window, resets_at, used_percentage)`.
- **`account_timeline(ts, window IN ('5h','7d'), used_percentage REAL, resets_at INTEGER)`**
  — `db.py:94`. `used_percentage` is already **0–100** (not a fraction).
- **It is currently EMPTY (0 rows).** The statusline capture block
  (`scripts/setup-statusline.sh`) has not been applied on any box, so Metric A
  has no data until the user wires it. See "User actions" below.
- Pipeline already exists end to end: statusline writes `~/.claude/rate-limits.jsonl`
  → `pull_rate_limit_log` rsyncs it (`pull.py:67`, gated on `machine.rate_limit_log`
  in `config/machines.toml`) → `ingest_ratelimits_file` loads `account_timeline`
  (`ratelimits.py:105`).
- Read helpers already exist: `rollups.plan_status(conn)` → latest row per window;
  `rollups.plan_timeline(conn, window, since=None)` → ordered series
  (`rollups.py`). The `/plan` page (`web/templates/plan.html`) already renders
  current % + a raw-snapshot strip. **Reuse these; do not duplicate.**
- API-equivalent value ($) per range is `rollups.overview(conn, **filters)["cost_usd"]`.
- Web reads a WAL DB with `PRAGMA query_only` on a **read-write** mount
  (`web/app.py:61`). Host dashboard port is **8765**. Tests run via
  `.venv/bin/python -m pytest` (no mise needed for tests).

---

## Metric A — Plan utilization ("value realized", PRIMARY)
Source: `account_timeline.used_percentage`, single account.

**Current gauges (Overview):** elevate the 5h and 7d current `used_percentage`
from `/plan` onto the Overview as two compact meters, labelled so 100% reads as
"limit reached / full value." Reuse `plan_status`. Keep the fuller `/plan` page.

**Period summary (over the Overview date filter):** add a rollup, e.g.
`rollups.value_realized(conn, *, start_day, end_day)` returning, per window:
- `peak_pct` — max `used_percentage` in range,
- `avg_pct` — mean `used_percentage` across snapshots in range,
- `windows_realized` — count of DISTINCT `resets_at` whose peak `used_percentage`
  reached a "full" threshold (**default ≥ 95%** — make it a module constant),
- `windows_total` — count of DISTINCT `resets_at` seen in range.

"You fully used N of M five-hour windows" is the headline sentence for A.

**Reconciliation:** `used_percentage` values and `resets_at` grouping in the
rollup must match a raw `sqlite3` query over `account_timeline` for the same
range. (Cannot be verified until the table has rows — see fallback + user action.)

### Fallback when `account_timeline` is empty/stale (OPTIONAL, label "estimated")
From the Maciek trust hierarchy, tier 3: estimate utilization from ingested
`events` tokens in the trailing window ÷ a fixed Max5 ceiling. 5h ceiling ≈
**88,000 tokens**. **The 7d token ceiling is not reliably known — do NOT
fabricate one;** either ship 5h-only estimation or omit the fallback and instead
render an empty-state that nudges the user to wire the statusline. Prefer the
nudge over a wrong 7d number. Any estimated value MUST be visually flagged
`estimated`.

---

## CONFIRMED subscription facts (user, 2026-07-02) — LIFETIME framing chosen
Two plan periods; ROI headline = **all-time value ÷ total paid across both**:
- **Pro:** started 2026-03-24 → 2026-05-29. Monthly price + payment count TBD
  (assume Claude Pro $20/mo, ~2 payments ≈ $40 until user confirms).
- **Max5:** started 2026-05-29, ongoing. **$100.00/mo, paid 2× = $200.00.**
- Value split (verified against DB): all-time **$1,234.56**; Pro window **$61.73**;
  Max5 window **$1,172.83** (~95%). Lifetime ROI ≈ **20x** (pending exact Pro $).
- **Config must be MULTI-PERIOD** (`[[subscription.periods]]` list: plan,
  monthly_usd, started_on, optional ended_on), NOT single-rate. `subscription_roi`
  sums each period's cost. The reviewer (Claude) owns this refactor of the
  subagent's single-rate base.

## Metric B — Subscription ROI (COMPANION, no new capture, build this)
Works against data already in the DB — no statusline dependency.

`value_ratio = API-equivalent value ($ over period) ÷ subscription cost ($ over
same period)`.

- Single account → single subscription line. Add config (e.g. a `[subscription]`
  block in `config/machines.toml`, mirrored into `machines.example.toml`):
  `monthly_usd` and `started_on` (ISO date). **Max5 monthly price and start date:
  confirm with the user** — do not hardcode a guess.
- Subscription cost over the period = `monthly_usd × (months overlapping the
  selected range, or since `started_on`)`.
- Present near the headline: e.g. *"$1,234 API-equivalent value · ~$X paid · **Nx
  return**."* This is the "is it worth it" number and should read prominently.
- Degrade gracefully: if `[subscription]` is unset, hide B (no crash, no zero-div).

---

## Deliverables checklist
1. `rollups.value_realized(...)` (+ constant `WINDOW_FULL_PCT = 95`), unit-covered.
2. `rollups.subscription_roi(conn, monthly_usd, started_on, *, start_day, end_day)`
   returning `{api_value_usd, subscription_usd, ratio, months}`; None-safe.
3. Config parsing for the optional `[subscription]` block in `config.py`
   (+ example in `machines.example.toml`). Keep it optional.
4. Overview wiring: extend `_dashboard_context` (both the populated and the
   `conn is None` empty branches — see how M1 added `freshness`) with the two
   gauges + period summary + ROI line. Add any needed Jinja filters.
5. Templates: gauges/meters reuse the existing `.bar-track`/`.bar-fill` +
   `.plan-meter` CSS from `plan.html`; add a small "value" card cluster. Follow
   `dataviz` skill guidance for the meters (accessible, light+dark).
6. Tests mirroring `tests/test_web.py` / `tests/test_ratelimits.py`: seed
   `account_timeline` + events fixtures, assert rollup math and that gauges render;
   assert graceful empty/estimated states.

## User actions (block full verification of A; do first)
- Run `scripts/setup-statusline.sh` (dry-run, then `--apply`) on a box whose
  Claude account is the shared Max5 account, and set `rate_limit_log` for at least
  one machine in `config/machines.toml`, so `account_timeline` starts filling.
  Single account → one machine is enough, but wiring all four gives denser
  snapshots.
- Provide **Max5 monthly price** and **subscription start date** for Metric B.

## Open decisions to confirm before/at implementation
- A's "full window" threshold (default 95%) and whether the period summary leads
  with `windows_realized` (count) or `avg_pct`.
- Ship the token-estimate fallback (5h-only) or the empty-state nudge? (Recommend
  nudge; estimate is imprecise and 7d has no trustworthy ceiling.)
- Whether ROI (B) or utilization (A) sits higher on the page. (Recommend B higher
  — it works today and is the sharper "worth it?" answer; A fills in once wired.)

## Verify (reviewer, after implementation)
- `rollups.value_realized` and `subscription_roi` reconciled against raw `sqlite3`
  queries on a copy of `data/cus.db` (same pattern as the M1 recompute check).
- `.venv/bin/python -m pytest -q` green.
- Live render via `fastapi.testclient` against `data/cus.db`: gauges + ROI present
  when data/config exist; clean empty-states when they don't.
