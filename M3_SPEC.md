# M3 SPEC — Insights & Trends

> Untracked scratch spec for the implementer (Sonnet subagent; Codex is
> unavailable). Architect/reviewer = Claude: delegate, then **reconcile results
> against raw data** — do not trust the implementer's own tests. Work on branch
> `v2-m3` (off `main`, which now has M1+M2). Context in `HANDOFF.md`, `M2_SPEC.md`,
> and project memory.

## Objective
A new **Trends** view surfacing how usage evolves over time, using ONLY the
existing `events` table (3+ months of history, 2026-03-26 → now). No dependency
on `account_timeline` (still empty until the statusline is wired). Ideas mined
from ccusage / Maciek's monitor: trajectory, cache-efficiency trend, model
migration.

**Explicitly DEFERRED to M3.5 (do NOT build now):** burn-rate velocity and
forecast-to-ceiling — those need live `account_timeline` snapshots, which don't
exist yet. Note this in the Trends page as a one-line "coming once plan snapshots
are captured" pointer to `/plan`, nothing more.

## Ground-truth facts (verified)
- `events(ts TEXT iso8601, model, cost_usd REAL NULL, input/output/cache_* tokens, machine_id, is_sidechain, ...)`. `ts` is ISO like `2026-06-20T03:28:40.292Z`; day = `substr(ts,1,10)`.
- Existing rollups to EXTEND for consistency (read them first): `rollups.by_day` (daily cost/tokens, supports machine/start/end filters via `_filters`), `rollups.cache_savings` (point-in-time effective discount using `pricing.load_prices`, `CACHE_READ_MULTIPLIER`, `_model_id_candidates`), `rollups.by_model`, `rollups.TOKEN_EXPR`. Reuse `_filters(...)` and `_rows(...)`.
- Web: `web/app.py` filters (`intfmt`/`cost`/`tokens`/`pct`/`percent`/`ratio`), `_dashboard_context`/`_highlights_context` patterns (fill BOTH the populated and `conn is None` empty branches — see how M1/M2 did it). Charts are **accessible CSS bars** (`.bar-track`/`.bar-fill`, `.hour-strip`/`.hour-column` in `static/style.css`) — NO JS charting library. Host reads DB read-only (`PRAGMA query_only`), port 8765.
- Verified value split for sanity checks: all-time $1,234.56; the vast majority is in the last ~5 weeks (Max5 era). Weekly totals should reflect a sharp recent ramp.
- Tests run via `.venv/bin/python -m pytest -q` (currently **65 passing** — keep them green). Mirror `tests/test_web.py`, `tests/test_rollups.py` fixtures (seed `events` rows with explicit `ts`/`cost_usd`).

## Deliverables
1. **Rollups** (in `rollups.py`, all accept `*, machine=None, start_day=None, end_day=None` and reuse `_filters`):
   - `by_week(conn, ...)` — per ISO week (`strftime('%Y-%W', ts)` or equivalent; label with the week's Monday date): events, tokens, `cost_usd`, plus **week-over-week %change** in cost (compute in Python over the ordered rows; first week's delta = None).
   - `cost_trend(conn, window=7, ...)` — daily series (reuse `by_day`) annotated with a **trailing N-day moving average** of `cost_usd` (compute in Python; expose `cost_usd` and `cost_ma`). Used for the trajectory chart.
   - `cache_efficiency_timeline(conn, by='week', ...)` — effective cache-discount % per period (day or week). Turn the point-in-time `cache_savings` logic into a per-bucket series: for each bucket, `saved/(cost+saved)` using the same pricing math. Keep it correct, not approximate.
   - `model_mix_timeline(conn, by='week', top=6, ...)` — cost per model per period (for a stacked/segmented bar showing migration); bucket rarer models into `<other>`.
2. **Route + template**: `GET /trends` (+ nav link in `base.html` after "Highlights"), new `templates/trends.html` extending `base.html`, with: the daily-cost + moving-average chart, the weekly table (with WoW %), the cache-efficiency-over-time bars, and the model-mix-over-time segmented bars. Respect the same machine/date filter form the Overview uses (optional but preferred; if included, wire an htmx partial like the Overview does).
3. **Empty/edge states**: no data → clean empty-state, no crashes; unpriced events (`cost_usd IS NULL`) handled like existing rollups (treated as 0 in sums).
4. **Tests**: mirror existing suites — seed multi-week `events`, assert `by_week` buckets + WoW math, `cost_trend` moving-average values, `cache_efficiency_timeline` matches a hand-computed discount for a seeded bucket, `model_mix_timeline` bucketing + `<other>` rollup, and that `/trends` renders 200 with and without data.

## Constraints
- No new dependencies (stdlib + FastAPI/Jinja/htmx). Python 3.12, `from __future__ import annotations`. Match existing code style exactly.
- Charts: reuse the existing accessible CSS-bar vocabulary; if you invoke the `dataviz` skill for palette/accessibility guidance, still keep to the project's CSS-variable palette (`--accent`, `--accent-soft`, etc.) and light+dark support already in `style.css`. No canvas/svg-lib/JS charts.
- Web code must not write to the DB.

## Report back (do NOT git commit — reviewer commits)
Files changed, new function signatures, exact `pytest` output, how you verified each rollup's math (hand-computed against seeded fixtures AND, where possible, cross-checked `cache_efficiency_timeline` against the existing `cache_savings` total), and any deviations/assumptions (e.g. ISO-week labeling choice). Be explicit about anything unverified.

## Verify (reviewer, after implementation)
- Reconcile `by_week`/`model_mix_timeline`/`cache_efficiency_timeline` against raw SQL on a copy of `data/cus.db` (weekly cost sums to all-time $1,234.56; cache-efficiency weeks aggregate consistently with `cache_savings`).
- `.venv/bin/python -m pytest -q` green.
- Live-render `/trends` against `data/cus.db` via `fastapi.testclient`; confirm the recent Max5-era ramp is visible and no template errors.
