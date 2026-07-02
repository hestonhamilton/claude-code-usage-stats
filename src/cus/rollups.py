from __future__ import annotations

import calendar
import sqlite3
from collections.abc import Sequence
from datetime import date, timedelta
from typing import Any

from .pricing import CACHE_READ_MULTIPLIER, _model_id_candidates, load_prices


TOKEN_EXPR = """
COALESCE(input_tokens, 0)
+ COALESCE(output_tokens, 0)
+ COALESCE(cache_creation_tokens, 0)
+ COALESCE(cache_read_tokens, 0)
"""

# "Full window" threshold for Metric A (value realized / plan utilization):
# a resets_at window whose peak used_percentage reaches this is counted as
# fully used ("100% value extracted"). See M2 spec.
WINDOW_FULL_PCT = 95


def _rows(cursor: sqlite3.Cursor) -> list[dict[str, Any]]:
    return [dict(row) for row in cursor.fetchall()]


def _filters(
    machine: str | None = None,
    start_day: str | None = None,
    end_day: str | None = None,
    table_alias: str | None = None,
) -> tuple[str, list[Any]]:
    prefix = f"{table_alias}." if table_alias else ""
    clauses: list[str] = []
    params: list[Any] = []
    if machine:
        clauses.append(f"{prefix}machine_id = ?")
        params.append(machine)
    if start_day:
        clauses.append(f"substr({prefix}ts, 1, 10) >= ?")
        params.append(start_day)
    if end_day:
        clauses.append(f"substr({prefix}ts, 1, 10) <= ?")
        params.append(end_day)
    return ("WHERE " + " AND ".join(clauses)) if clauses else "", params


def overview(
    conn: sqlite3.Connection,
    *,
    machine: str | None = None,
    start_day: str | None = None,
    end_day: str | None = None,
) -> dict[str, Any]:
    where, params = _filters(machine, start_day, end_day)
    row = conn.execute(
        f"""
        SELECT
            COUNT(*) AS events,
            COUNT(DISTINCT session_id) AS sessions,
            COUNT(DISTINCT machine_id) AS machines,
            COALESCE(SUM(input_tokens), 0) AS input_tokens,
            COALESCE(SUM(output_tokens), 0) AS output_tokens,
            COALESCE(SUM(cache_creation_tokens), 0) AS cache_creation_tokens,
            COALESCE(SUM(cache_read_tokens), 0) AS cache_read_tokens,
            COALESCE(SUM(cost_usd), 0) AS cost_usd,
            SUM(CASE WHEN cost_usd IS NULL THEN 1 ELSE 0 END) AS unpriced_events,
            MIN(ts) AS first_ts,
            MAX(ts) AS last_ts
        FROM events
        {where}
        """,
        params,
    ).fetchone()
    data = dict(row)
    data["total_tokens"] = (
        data["input_tokens"]
        + data["output_tokens"]
        + data["cache_creation_tokens"]
        + data["cache_read_tokens"]
    )
    data["unpriced_events"] = data["unpriced_events"] or 0
    return data


def by_day(
    conn: sqlite3.Connection,
    days: int | None = None,
    *,
    machine: str | None = None,
    start_day: str | None = None,
    end_day: str | None = None,
) -> list[dict[str, Any]]:
    where, params = _filters(machine, start_day, end_day)
    limit = ""
    if days is not None:
        limit = "LIMIT ?"
        params.append(days)
    rows = _rows(
        conn.execute(
            f"""
            SELECT
                substr(ts, 1, 10) AS day,
                COUNT(*) AS events,
                COALESCE(SUM({TOKEN_EXPR}), 0) AS tokens,
                COALESCE(SUM(cost_usd), 0) AS cost_usd
            FROM events
            {where}
            GROUP BY day
            ORDER BY day DESC
            {limit}
            """,
            params,
        )
    )
    rows.reverse()
    return rows


def _week_start(day: str) -> date:
    """Monday of the ISO week containing `day` (a 'YYYY-MM-DD' string)."""
    parsed = date.fromisoformat(day)
    return parsed - timedelta(days=parsed.weekday())


def by_week(
    conn: sqlite3.Connection,
    *,
    machine: str | None = None,
    start_day: str | None = None,
    end_day: str | None = None,
) -> list[dict[str, Any]]:
    """Per-ISO-week rollup (events/tokens/cost) with week-over-week %change.

    Buckets `by_day(...)` rows by the Monday of each row's ISO week (Mon-Sun),
    so a week is labeled `week` = that Monday's date, matching M3 spec's
    "label with the week's Monday date". `wow_pct_change` is a **fraction**
    (e.g. 0.25 for +25%), consistent with the existing `effective_discount_pct`
    / `pct_cost` convention for Python-computed ratios (as opposed to
    pre-scaled columns like `used_percentage`); it is None for the first week
    in range and also None when the prior week's cost was 0 (no baseline to
    compare against, avoids a division by zero / infinite jump).
    """
    days = by_day(conn, machine=machine, start_day=start_day, end_day=end_day)
    buckets: dict[date, dict[str, Any]] = {}
    order: list[date] = []
    for row in days:
        monday = _week_start(row["day"])
        if monday not in buckets:
            buckets[monday] = {
                "week": monday.isoformat(),
                "events": 0,
                "tokens": 0,
                "cost_usd": 0.0,
            }
            order.append(monday)
        bucket = buckets[monday]
        bucket["events"] += row["events"]
        bucket["tokens"] += row["tokens"]
        bucket["cost_usd"] += row["cost_usd"]
    order.sort()
    result: list[dict[str, Any]] = []
    prev_cost: float | None = None
    for monday in order:
        bucket = buckets[monday]
        if prev_cost is None or prev_cost == 0:
            bucket["wow_pct_change"] = None
        else:
            bucket["wow_pct_change"] = (bucket["cost_usd"] - prev_cost) / prev_cost
        prev_cost = bucket["cost_usd"]
        result.append(bucket)
    return result


def cost_trend(
    conn: sqlite3.Connection,
    window: int = 7,
    *,
    machine: str | None = None,
    start_day: str | None = None,
    end_day: str | None = None,
) -> list[dict[str, Any]]:
    """Daily cost series (reuses `by_day`) annotated with a trailing
    `window`-day moving average `cost_ma`, for the trajectory chart.

    The average uses a growing window at the start of the range (day 1 of the
    range averages just itself, day 2 averages days 1-2, ...) rather than
    requiring a full `window` days of history before emitting a value — this
    keeps the whole filtered range plottable with no leading gap/None run.
    """
    days = by_day(conn, machine=machine, start_day=start_day, end_day=end_day)
    costs = [row["cost_usd"] for row in days]
    result: list[dict[str, Any]] = []
    for i, row in enumerate(days):
        segment = costs[max(0, i - window + 1) : i + 1]
        cost_ma = sum(segment) / len(segment) if segment else 0.0
        result.append({**row, "cost_ma": cost_ma})
    return result


def _breakdown(
    conn: sqlite3.Connection,
    column: str,
    label: str,
    *,
    machine: str | None = None,
    start_day: str | None = None,
    end_day: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    where, params = _filters(machine, start_day, end_day)
    limit_sql = ""
    if limit is not None:
        limit_sql = "LIMIT ?"
        params.append(limit)
    return _rows(
        conn.execute(
            f"""
            SELECT
                COALESCE({column}, '<unknown>') AS {label},
                COUNT(*) AS events,
                COUNT(DISTINCT session_id) AS sessions,
                COALESCE(SUM({TOKEN_EXPR}), 0) AS tokens,
                COALESCE(SUM(cost_usd), 0) AS cost_usd
            FROM events
            {where}
            GROUP BY {column}
            ORDER BY cost_usd DESC, tokens DESC, events DESC, {label}
            {limit_sql}
            """,
            params,
        )
    )


def by_model(conn: sqlite3.Connection, **filters: Any) -> list[dict[str, Any]]:
    return _breakdown(conn, "model", "model", **filters)


def by_machine(conn: sqlite3.Connection, **filters: Any) -> list[dict[str, Any]]:
    return _breakdown(conn, "machine_id", "machine_id", **filters)


def by_project(conn: sqlite3.Connection, **filters: Any) -> list[dict[str, Any]]:
    return _breakdown(conn, "cwd", "cwd", **filters)


def by_branch(conn: sqlite3.Connection, **filters: Any) -> list[dict[str, Any]]:
    return _breakdown(conn, "git_branch", "git_branch", **filters)


def model_mix_timeline(
    conn: sqlite3.Connection,
    *,
    by: str = "week",
    top: int = 6,
    machine: str | None = None,
    start_day: str | None = None,
    end_day: str | None = None,
) -> dict[str, Any]:
    """Cost per model per period, for the model-migration segmented bar.

    Models are ranked by total cost over the WHOLE filtered range (not
    per-bucket) and the top `top` keep their own series; every other model
    (including untracked/null, which `by_model` et al. label `<unknown>`) is
    folded into a single `<other>` series per bucket — so a model's series
    identity is stable across buckets (a model doesn't hop between being its
    own segment and `<other>` from one period to the next). Ties in total
    cost break alphabetically for determinism.

    Returns `{"top_models": [...], "periods": [...]}`:
    - `top_models`: the ordered list of series names actually rendered
      (top-cost models first, `<other>` last if any bucket needed it) — a
      stable legend/series order for the template to iterate.
    - `periods`: one dict per bucket, keyed by `by` (`"week"` or `"day"`,
      matching `by_week`/`cache_efficiency_timeline`'s field naming) plus
      `cost_usd` (bucket total) and `models` (dict of series name -> cost_usd
      for every series in `top_models`, 0.0 if absent that period).
    """
    if by not in {"day", "week"}:
        raise ValueError("by must be 'day' or 'week'")
    where, params = _filters(machine, start_day, end_day)
    rows = _rows(
        conn.execute(
            f"""
            SELECT
                substr(ts, 1, 10) AS day,
                COALESCE(model, '<unknown>') AS model,
                COALESCE(SUM(cost_usd), 0) AS cost_usd
            FROM events
            {where}
            GROUP BY day, model
            """,
            params,
        )
    )

    totals: dict[str, float] = {}
    for row in rows:
        totals[row["model"]] = totals.get(row["model"], 0.0) + row["cost_usd"]
    top_models = sorted(totals, key=lambda m: (-totals[m], m))[:top]
    top_set = set(top_models)

    buckets: dict[str, dict[str, float]] = {}
    order: list[str] = []
    used_other = False
    for row in rows:
        key = row["day"] if by == "day" else _week_start(row["day"]).isoformat()
        if key not in buckets:
            buckets[key] = {}
            order.append(key)
        series = row["model"] if row["model"] in top_set else "<other>"
        used_other = used_other or series == "<other>"
        buckets[key][series] = buckets[key].get(series, 0.0) + row["cost_usd"]
    order.sort()

    series_names = [*top_models, "<other>"] if used_other else list(top_models)
    periods: list[dict[str, Any]] = []
    for key in order:
        bucket = buckets[key]
        models = {name: bucket.get(name, 0.0) for name in series_names}
        periods.append({by: key, "cost_usd": sum(models.values()), "models": models})

    return {"top_models": series_names, "periods": periods}


def cache_savings(
    conn: sqlite3.Connection,
    *,
    machine: str | None = None,
    start_day: str | None = None,
    end_day: str | None = None,
) -> dict[str, Any]:
    prices = load_prices()
    where, params = _filters(machine, start_day, end_day)
    rows = conn.execute(
        f"""
        SELECT model, cache_read_tokens, cost_usd
        FROM events
        {where}
        """,
        params,
    )
    cache_read_tokens = 0
    cost_usd = 0.0
    saved_usd = 0.0
    for row in rows:
        model = row["model"] or ""
        rates = next((prices[c] for c in _model_id_candidates(model) if c in prices), None)
        if rates is None:
            continue
        event_cache_read_tokens = row["cache_read_tokens"] or 0
        cache_read_tokens += event_cache_read_tokens
        cost_usd += row["cost_usd"] or 0.0
        saved_usd += (
            event_cache_read_tokens
            * rates["input_cost_per_token"]
            * (1.0 - CACHE_READ_MULTIPLIER)
        )
    denominator = cost_usd + saved_usd
    return {
        "cache_read_tokens": cache_read_tokens,
        "cost_usd": cost_usd,
        "saved_usd": saved_usd,
        "effective_discount_pct": saved_usd / denominator if denominator else 0.0,
    }


def cache_efficiency_timeline(
    conn: sqlite3.Connection,
    *,
    by: str = "week",
    machine: str | None = None,
    start_day: str | None = None,
    end_day: str | None = None,
) -> list[dict[str, Any]]:
    """Per-bucket effective cache-discount %, using the SAME pricing math as
    `cache_savings` (same `load_prices`/`_model_id_candidates`/
    `CACHE_READ_MULTIPLIER` logic, just accumulated per day/week bucket
    instead of once over the whole filtered range). Summing every bucket's
    `cache_read_tokens`/`cost_usd`/`saved_usd` reproduces `cache_savings`'
    totals for the same filters exactly (see tests).

    `by` is `"week"` (bucketed to the ISO week's Monday, like `by_week`) or
    `"day"`. Each result row is keyed by `by` (i.e. has a `"week"` or `"day"`
    field) holding the bucket label, matching `by_week`/`by_day`'s own field
    naming.
    """
    if by not in {"day", "week"}:
        raise ValueError("by must be 'day' or 'week'")
    prices = load_prices()
    where, params = _filters(machine, start_day, end_day)
    rows = conn.execute(
        f"""
        SELECT substr(ts, 1, 10) AS day, model, cache_read_tokens, cost_usd
        FROM events
        {where}
        """,
        params,
    )
    buckets: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for row in rows:
        key = row["day"] if by == "day" else _week_start(row["day"]).isoformat()
        if key not in buckets:
            buckets[key] = {"cache_read_tokens": 0, "cost_usd": 0.0, "saved_usd": 0.0}
            order.append(key)
        bucket = buckets[key]
        model = row["model"] or ""
        rates = next((prices[c] for c in _model_id_candidates(model) if c in prices), None)
        if rates is None:
            continue
        event_cache_read_tokens = row["cache_read_tokens"] or 0
        bucket["cache_read_tokens"] += event_cache_read_tokens
        bucket["cost_usd"] += row["cost_usd"] or 0.0
        bucket["saved_usd"] += (
            event_cache_read_tokens
            * rates["input_cost_per_token"]
            * (1.0 - CACHE_READ_MULTIPLIER)
        )
    order.sort()
    result: list[dict[str, Any]] = []
    for key in order:
        bucket = buckets[key]
        denominator = bucket["cost_usd"] + bucket["saved_usd"]
        result.append(
            {
                by: key,
                "cache_read_tokens": bucket["cache_read_tokens"],
                "cost_usd": bucket["cost_usd"],
                "saved_usd": bucket["saved_usd"],
                "effective_discount_pct": (
                    bucket["saved_usd"] / denominator if denominator else 0.0
                ),
            }
        )
    return result


def by_hour(
    conn: sqlite3.Connection,
    *,
    machine: str | None = None,
    start_day: str | None = None,
    end_day: str | None = None,
) -> list[dict[str, Any]]:
    where, params = _filters(machine, start_day, end_day)
    rows = {
        int(row["hour"]): dict(row)
        for row in conn.execute(
            f"""
            SELECT
                CAST(substr(ts, 12, 2) AS INTEGER) AS hour,
                COUNT(*) AS events,
                COALESCE(SUM({TOKEN_EXPR}), 0) AS tokens,
                COALESCE(SUM(cost_usd), 0) AS cost_usd
            FROM events
            {where}
            GROUP BY hour
            """,
            params,
        )
        if row["hour"] is not None
    }
    return [
        rows.get(hour, {"hour": hour, "events": 0, "tokens": 0, "cost_usd": 0.0})
        for hour in range(24)
    ]


def sidechain_share(
    conn: sqlite3.Connection,
    *,
    machine: str | None = None,
    start_day: str | None = None,
    end_day: str | None = None,
) -> dict[str, Any]:
    where, params = _filters(machine, start_day, end_day)
    row = conn.execute(
        f"""
        SELECT
            COUNT(*) AS events,
            COALESCE(SUM(CASE WHEN is_sidechain = 1 THEN 1 ELSE 0 END), 0) AS sidechain_events,
            COALESCE(SUM(cost_usd), 0) AS cost_usd,
            COALESCE(SUM(CASE WHEN is_sidechain = 1 THEN cost_usd ELSE 0 END), 0)
                AS sidechain_cost_usd
        FROM events
        {where}
        """,
        params,
    ).fetchone()
    data = dict(row)
    data["pct_cost"] = (
        data["sidechain_cost_usd"] / data["cost_usd"] if data["cost_usd"] else 0.0
    )
    return data


def server_tool_usage(
    conn: sqlite3.Connection,
    *,
    machine: str | None = None,
    start_day: str | None = None,
    end_day: str | None = None,
) -> dict[str, Any]:
    where, params = _filters(machine, start_day, end_day)
    row = conn.execute(
        f"""
        SELECT
            COALESCE(SUM(web_search), 0) AS web_search_requests,
            COALESCE(SUM(web_fetch), 0) AS web_fetch_requests
        FROM events
        {where}
        """,
        params,
    ).fetchone()
    return dict(row)


def most_expensive_prompts(
    conn: sqlite3.Connection,
    limit: int = 10,
    *,
    machine: str | None = None,
    start_day: str | None = None,
    end_day: str | None = None,
) -> list[dict[str, Any]]:
    where, params = _filters(machine, start_day, end_day)
    extra = "cost_usd IS NOT NULL"
    if where:
        where = f"{where} AND {extra}"
    else:
        where = f"WHERE {extra}"
    params.append(limit)
    return _rows(
        conn.execute(
            f"""
            SELECT uuid, session_id, machine_id, model, ts, cost_usd
            FROM events
            {where}
            ORDER BY cost_usd DESC, ts DESC, uuid
            LIMIT ?
            """,
            params,
        )
    )


def top_sessions(
    conn: sqlite3.Connection,
    limit: int = 20,
    order_by: str = "cost",
    *,
    machine: str | None = None,
    start_day: str | None = None,
    end_day: str | None = None,
) -> list[dict[str, Any]]:
    where, params = _session_filters(machine, start_day, end_day)
    order_sql = "COALESCE(cost_usd, 0) DESC, last_ts DESC"
    if order_by == "recent":
        order_sql = "last_ts DESC, COALESCE(cost_usd, 0) DESC"
    params.append(limit)
    return _rows(
        conn.execute(
            f"""
            SELECT
                session_id, machine_id, cwd, title, message_count,
                cost_usd, last_ts
            FROM sessions
            {where}
            ORDER BY {order_sql}
            LIMIT ?
            """,
            params,
        )
    )


def recent_sessions(conn: sqlite3.Connection, limit: int = 50) -> list[dict[str, Any]]:
    return top_sessions(conn, limit=limit, order_by="recent")


def session_detail(conn: sqlite3.Connection, session_id: str) -> dict[str, Any] | None:
    session = conn.execute(
        "SELECT * FROM sessions WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    if session is None:
        return None
    model_breakdown = _rows(
        conn.execute(
            f"""
            SELECT
                COALESCE(model, '<unknown>') AS model,
                COUNT(*) AS events,
                COALESCE(SUM(input_tokens), 0) AS input_tokens,
                COALESCE(SUM(output_tokens), 0) AS output_tokens,
                COALESCE(SUM(cache_creation_tokens), 0) AS cache_creation_tokens,
                COALESCE(SUM(cache_read_tokens), 0) AS cache_read_tokens,
                COALESCE(SUM({TOKEN_EXPR}), 0) AS tokens,
                COALESCE(SUM(cost_usd), 0) AS cost_usd
            FROM events
            WHERE session_id = ?
            GROUP BY model
            ORDER BY cost_usd DESC, tokens DESC, events DESC, model
            """,
            (session_id,),
        )
    )
    bounds = conn.execute(
        "SELECT MIN(ts) AS first_ts, MAX(ts) AS last_ts FROM events WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    split = conn.execute(
        f"""
        SELECT
            COUNT(*) AS events,
            COALESCE(SUM({TOKEN_EXPR}), 0) AS tokens,
            COALESCE(SUM(cost_usd), 0) AS cost_usd,
            COALESCE(SUM(CASE WHEN is_sidechain = 1 THEN 1 ELSE 0 END), 0)
                AS subagent_events,
            COALESCE(SUM(CASE WHEN is_sidechain = 1 THEN {TOKEN_EXPR} ELSE 0 END), 0)
                AS subagent_tokens,
            COALESCE(SUM(CASE WHEN is_sidechain = 1 THEN cost_usd ELSE 0 END), 0)
                AS subagent_cost_usd
        FROM events
        WHERE session_id = ?
        """,
        (session_id,),
    ).fetchone()
    subagent = dict(split)
    subagent["pct_cost"] = (
        subagent["subagent_cost_usd"] / subagent["cost_usd"]
        if subagent["cost_usd"]
        else 0.0
    )
    data = dict(session)
    data["model_breakdown"] = model_breakdown
    data["subagent"] = subagent
    data["tool_use_mix"] = tool_use_mix(conn, session_id=session_id)
    data["first_ts"] = bounds["first_ts"] or data["first_ts"]
    data["last_ts"] = bounds["last_ts"] or data["last_ts"]
    data["total_tokens"] = (
        (data["input_tokens"] or 0)
        + (data["output_tokens"] or 0)
        + (data["cache_creation_tokens"] or 0)
        + (data["cache_read_tokens"] or 0)
    )
    return data


def tool_use_mix(
    conn: sqlite3.Connection,
    session_id: str | None = None,
    *,
    machine: str | None = None,
    start_day: str | None = None,
    end_day: str | None = None,
) -> list[dict[str, Any]]:
    where, params = _filters(machine, start_day, end_day, table_alias="e")
    if session_id is not None:
        if where:
            where += " AND e.session_id = ?"
        else:
            where = "WHERE e.session_id = ?"
        params.append(session_id)
    return _rows(
        conn.execute(
            f"""
            SELECT t.tool_name, COUNT(*) AS count
            FROM tool_uses AS t
            JOIN events AS e ON e.uuid = t.event_uuid
            {where}
            GROUP BY t.tool_name
            ORDER BY count DESC, t.tool_name
            """,
            params,
        )
    )


def _session_filters(
    machine: str | None = None,
    start_day: str | None = None,
    end_day: str | None = None,
) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if machine:
        clauses.append("machine_id = ?")
        params.append(machine)
    if start_day:
        clauses.append("substr(last_ts, 1, 10) >= ?")
        params.append(start_day)
    if end_day:
        clauses.append("substr(last_ts, 1, 10) <= ?")
        params.append(end_day)
    return ("WHERE " + " AND ".join(clauses)) if clauses else "", params


def machines(conn: sqlite3.Connection) -> list[str]:
    return [
        row["machine_id"]
        for row in conn.execute(
            "SELECT DISTINCT machine_id FROM events WHERE machine_id IS NOT NULL ORDER BY machine_id"
        )
    ]


def freshness(conn: sqlite3.Connection) -> dict[str, Any]:
    """When the ingested snapshot was last refreshed, overall and per machine.

    The dashboard is a point-in-time snapshot; surfacing the most recent
    `last_ingest_at` makes clear the numbers may lag a live statusline.
    """
    rows = _rows(
        conn.execute(
            """
            SELECT machine_id, last_ingest_at
            FROM machines
            WHERE last_ingest_at IS NOT NULL
            ORDER BY last_ingest_at DESC, machine_id
            """
        )
    )
    return {
        "last_ingest_at": rows[0]["last_ingest_at"] if rows else None,
        "machines": rows,
    }


def plan_status(conn: sqlite3.Connection) -> dict[str, dict[str, Any] | None]:
    status: dict[str, dict[str, Any] | None] = {"5h": None, "7d": None}
    for window in status:
        row = conn.execute(
            """
            SELECT ts, used_percentage, resets_at
            FROM account_timeline
            WHERE window = ?
            ORDER BY ts DESC
            LIMIT 1
            """,
            (window,),
        ).fetchone()
        if row is not None:
            status[window] = dict(row)
    return status


def plan_timeline(
    conn: sqlite3.Connection,
    window: str,
    since: str | None = None,
) -> list[dict[str, Any]]:
    if window not in {"5h", "7d"}:
        raise ValueError("window must be '5h' or '7d'")
    where = "WHERE window = ?"
    params: list[Any] = [window]
    if since is not None:
        where += " AND ts >= ?"
        params.append(since)
    return _rows(
        conn.execute(
            f"""
            SELECT ts, used_percentage, resets_at
            FROM account_timeline
            {where}
            ORDER BY ts ASC
            """,
            params,
        )
    )


def _account_timeline_filters(
    start_day: str | None = None,
    end_day: str | None = None,
) -> tuple[str, list[Any]]:
    # account_timeline has no machine_id column: rate-limit snapshots describe
    # a single shared account across all machines (see M2 spec), so only the
    # date range applies here.
    clauses: list[str] = []
    params: list[Any] = []
    if start_day:
        clauses.append("substr(ts, 1, 10) >= ?")
        params.append(start_day)
    if end_day:
        clauses.append("substr(ts, 1, 10) <= ?")
        params.append(end_day)
    return ("WHERE " + " AND ".join(clauses)) if clauses else "", params


def value_realized(
    conn: sqlite3.Connection,
    *,
    machine: str | None = None,
    start_day: str | None = None,
    end_day: str | None = None,
) -> dict[str, dict[str, Any]]:
    """Metric A: plan-utilization rollup over `account_timeline`, per window.

    `machine` is accepted for filter-signature parity with the other rollups
    (the dashboard passes a shared `**filters` dict) but has no effect: the
    account is a single shared Max5 account across all machines, and
    `account_timeline` has no `machine_id` column.

    Per window (`5h`, `7d`):
    - `peak_pct` / `avg_pct`: max / mean `used_percentage` across all
      snapshots in range (None if no snapshots in range).
    - `windows_realized`: count of DISTINCT `resets_at` whose peak
      `used_percentage` reached `WINDOW_FULL_PCT`.
    - `windows_total`: count of DISTINCT `resets_at` seen in range.
    """
    del machine
    where, params = _account_timeline_filters(start_day, end_day)
    result: dict[str, dict[str, Any]] = {}
    for window in ("5h", "7d"):
        window_where = where + (" AND window = ?" if where else "WHERE window = ?")
        window_params = [*params, window]
        summary = conn.execute(
            f"""
            SELECT
                MAX(used_percentage) AS peak_pct,
                AVG(used_percentage) AS avg_pct,
                COUNT(DISTINCT resets_at) AS windows_total
            FROM account_timeline
            {window_where}
            """,
            window_params,
        ).fetchone()
        realized = conn.execute(
            f"""
            SELECT COUNT(*) AS windows_realized
            FROM (
                SELECT resets_at
                FROM account_timeline
                {window_where}
                GROUP BY resets_at
                HAVING MAX(used_percentage) >= ?
            )
            """,
            [*window_params, WINDOW_FULL_PCT],
        ).fetchone()
        result[window] = {
            "peak_pct": summary["peak_pct"],
            "avg_pct": summary["avg_pct"],
            "windows_realized": realized["windows_realized"] or 0,
            "windows_total": summary["windows_total"] or 0,
        }
    return result


def _add_months(anchor: date, k: int) -> date:
    """`anchor` shifted forward by `k` whole months, clamping overflowed days.

    (e.g. Jan 31 + 1 month -> Feb 28/29.) Billing anniversaries are computed
    from a plan's own start date, so the day-of-month is preserved where the
    target month is long enough.
    """
    total = anchor.month - 1 + k
    year = anchor.year + total // 12
    month = total % 12 + 1
    day = min(anchor.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _billing_cycles(anchor: date, window_start: date, window_end: date) -> int:
    """How many monthly charges (anniversaries of `anchor`) fall in the window.

    A subscription is charged on `anchor` and each monthly anniversary while
    active. Counting anniversaries — NOT calendar months touched — is what makes
    a plan started on the 29th and running ~5 weeks bill as 2 charges, matching
    what the card actually paid.
    """
    if window_end < window_start:
        return 0
    cycles = 0
    k = 0
    while True:
        charge = _add_months(anchor, k)
        if charge > window_end:
            break
        if charge >= window_start:
            cycles += 1
        k += 1
        if k > 1200:  # ~100 years: defensive cap, never reached in practice
            break
    return cycles


def subscription_roi(
    conn: sqlite3.Connection,
    periods: Sequence[Any] | None,
    *,
    start_day: str | None = None,
    end_day: str | None = None,
) -> dict[str, Any] | None:
    """Metric B: subscription ROI — API-equivalent value vs. subscription cost.

    `periods` is a sequence of objects with `monthly_usd: float`,
    `started_on: date`, `ended_on: date | None`, and optional `plan: str`
    (see `config.SubscriptionPeriod`). Multiple periods let the ROI span a
    plan change (e.g. Pro then Max5) honestly. Returns None (hide the metric,
    no crash/divide-by-zero) when `periods` is empty.

    `api_value_usd` reuses `overview(...)["cost_usd"]` for the same date-range
    filters (no `machine` filter: single shared account). Each period's cost is
    `monthly_usd x _billing_cycles(started_on, clipped window)`, where the
    window is the period's active life ([started_on, ended_on or today])
    intersected with any requested date range. `subscription_usd` sums them.
    """
    if not periods:
        return None

    api_value_usd = overview(conn, start_day=start_day, end_day=end_day)["cost_usd"] or 0.0

    range_start = date.fromisoformat(start_day) if start_day else None
    range_end = date.fromisoformat(end_day) if end_day else date.today()

    subscription_usd = 0.0
    total_cycles = 0
    breakdown: list[dict[str, Any]] = []
    for period in periods:
        active_end = period.ended_on or date.today()
        clip_start = period.started_on if range_start is None else max(period.started_on, range_start)
        clip_end = min(active_end, range_end)
        cycles = _billing_cycles(period.started_on, clip_start, clip_end)
        cost = period.monthly_usd * cycles
        subscription_usd += cost
        total_cycles += cycles
        breakdown.append(
            {
                "plan": getattr(period, "plan", None),
                "monthly_usd": period.monthly_usd,
                "cycles": cycles,
                "cost_usd": cost,
            }
        )

    ratio = (api_value_usd / subscription_usd) if subscription_usd else None
    return {
        "api_value_usd": api_value_usd,
        "subscription_usd": subscription_usd,
        "ratio": ratio,
        "cycles": total_cycles,
        "periods": breakdown,
    }
