from __future__ import annotations

import socket
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .models import AssistantEvent
from .parser import parse_file
from .pricing import cost_for, load_prices


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _usage_total(event: AssistantEvent) -> int:
    return (
        event.input_tokens
        + event.output_tokens
        + event.cache_creation_tokens
        + event.cache_read_tokens
    )


def _group_by_response(
    events: list[AssistantEvent],
) -> list[tuple[AssistantEvent, list[str]]]:
    """Collapse JSONL lines that belong to the same API response.

    Claude Code writes one JSONL line per content block (text/thinking/tool_use)
    but every line for a given response carries the same `message.usage` and
    `message.id`. The billing unit is one response, so group on `message_id`
    (falling back to `uuid` when it's absent) and keep the line with the
    largest total usage as the representative for usage/cost/model/etc. Tool
    names are collected from every line in the group.
    """
    order: list[object] = []
    groups: dict[object, dict[str, object]] = {}
    for event in events:
        key: object = ("message_id", event.message_id) if event.message_id else ("uuid", event.uuid)
        group = groups.get(key)
        if group is None:
            group = {"representative": event, "best_usage": _usage_total(event), "tool_uses": []}
            groups[key] = group
            order.append(key)
        elif _usage_total(event) > group["best_usage"]:
            group["representative"] = event
            group["best_usage"] = _usage_total(event)
        group["tool_uses"].extend(event.tool_uses)  # type: ignore[union-attr]

    return [(groups[key]["representative"], groups[key]["tool_uses"]) for key in order]  # type: ignore[misc]


def _stored_offset(conn: sqlite3.Connection, path: Path, size: int, mtime: float) -> int:
    row = conn.execute(
        "SELECT size, mtime, byte_offset FROM ingest_state WHERE path = ?",
        (str(path),),
    ).fetchone()
    if row is None:
        return 0
    if size < int(row["byte_offset"]) or size < int(row["size"]) or mtime < float(row["mtime"]):
        return 0
    return int(row["byte_offset"])


def _insert_event(
    conn: sqlite3.Connection,
    event,
    tool_uses: list[str],
    machine_id: str,
    prices: dict[str, dict[str, float]],
) -> tuple[bool, float | None]:
    cost_usd = cost_for(
        event.model,
        event.input_tokens,
        event.output_tokens,
        event.ephemeral_5m_tokens,
        event.ephemeral_1h_tokens,
        event.cache_read_tokens,
        event.cache_creation_tokens,
        prices,
    )
    cursor = conn.execute(
        """
        INSERT OR IGNORE INTO events (
            uuid, message_id, machine_id, session_id, ts, record_type, model, cwd, git_branch,
            is_sidechain, input_tokens, output_tokens, cache_creation_tokens,
            cache_read_tokens, ephemeral_1h_tokens, ephemeral_5m_tokens,
            service_tier, web_search, web_fetch, cost_usd
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event.uuid,
            event.message_id,
            machine_id,
            event.session_id,
            event.ts,
            event.record_type,
            event.model,
            event.cwd,
            event.git_branch,
            1 if event.is_sidechain else 0,
            event.input_tokens,
            event.output_tokens,
            event.cache_creation_tokens,
            event.cache_read_tokens,
            event.ephemeral_1h_tokens,
            event.ephemeral_5m_tokens,
            event.service_tier,
            event.web_search,
            event.web_fetch,
            cost_usd,
        ),
    )
    inserted = cursor.rowcount == 1
    if inserted:
        conn.executemany(
            "INSERT INTO tool_uses (event_uuid, tool_name) VALUES (?, ?)",
            [(event.uuid, name) for name in tool_uses],
        )
    return inserted, cost_usd


def recompute_sessions(conn: sqlite3.Connection, machine_id: str | None = None) -> None:
    """Rebuild the sessions rollup in a single set-based pass.

    One INSERT ... SELECT ... GROUP BY replaces the former per-session Python
    loop (two queries per session), so cost is O(rows) regardless of how many
    sessions exist. The latest title per session is resolved with a window
    function (ROW_NUMBER over session_titles, newest ts then rowid), matching
    the prior per-session `ORDER BY COALESCE(ts,'') DESC, rowid DESC LIMIT 1`.
    """
    params: tuple[str, ...] = ()
    where = ""
    if machine_id is not None:
        where = "WHERE e.machine_id = ?"
        params = (machine_id,)

    conn.execute(
        f"""
        INSERT INTO sessions (
            session_id, machine_id, cwd, title, first_ts, last_ts,
            input_tokens, output_tokens, cache_creation_tokens,
            cache_read_tokens, message_count, cost_usd
        )
        SELECT
            e.session_id,
            e.machine_id,
            e.cwd,
            t.title,
            MIN(e.ts) AS first_ts,
            MAX(e.ts) AS last_ts,
            COALESCE(SUM(e.input_tokens), 0) AS input_tokens,
            COALESCE(SUM(e.output_tokens), 0) AS output_tokens,
            COALESCE(SUM(e.cache_creation_tokens), 0) AS cache_creation_tokens,
            COALESCE(SUM(e.cache_read_tokens), 0) AS cache_read_tokens,
            COUNT(*) AS message_count,
            SUM(e.cost_usd) AS cost_usd
        FROM events AS e
        LEFT JOIN (
            SELECT session_id, title
            FROM (
                SELECT
                    session_id,
                    title,
                    ROW_NUMBER() OVER (
                        PARTITION BY session_id
                        ORDER BY COALESCE(ts, '') DESC, rowid DESC
                    ) AS rn
                FROM session_titles
            )
            WHERE rn = 1
        ) AS t ON t.session_id = e.session_id
        {where}
        GROUP BY e.session_id
        ON CONFLICT(session_id) DO UPDATE SET
            machine_id = excluded.machine_id,
            cwd = excluded.cwd,
            title = excluded.title,
            first_ts = excluded.first_ts,
            last_ts = excluded.last_ts,
            input_tokens = excluded.input_tokens,
            output_tokens = excluded.output_tokens,
            cache_creation_tokens = excluded.cache_creation_tokens,
            cache_read_tokens = excluded.cache_read_tokens,
            message_count = excluded.message_count,
            cost_usd = excluded.cost_usd
        """,
        params,
    )


def ingest_file(
    conn: sqlite3.Connection,
    path: str | Path,
    machine_id: str,
    prices: dict[str, dict[str, float]] | None = None,
    recompute: bool = True,
) -> dict[str, int | float]:
    if prices is None:
        prices = load_prices()
    file_path = Path(path)
    stat = file_path.stat()
    start_offset = _stored_offset(conn, file_path, stat.st_size, stat.st_mtime)
    result = parse_file(file_path, start_offset=start_offset)
    new_offset = stat.st_size
    inserted_events = 0
    inserted_tools = 0
    unpriced = 0
    cost_usd = 0.0

    with conn:
        conn.execute(
            """
            INSERT INTO machines (machine_id, hostname, label, last_ingest_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(machine_id) DO UPDATE SET
                hostname = excluded.hostname,
                last_ingest_at = excluded.last_ingest_at
            """,
            (machine_id, socket.gethostname(), machine_id, _utc_now()),
        )

        for event, tool_uses in _group_by_response(result.events):
            inserted, event_cost_usd = _insert_event(conn, event, tool_uses, machine_id, prices)
            if inserted:
                inserted_events += 1
                inserted_tools += len(tool_uses)
                if event_cost_usd is None:
                    unpriced += 1
                else:
                    cost_usd += event_cost_usd

        title_offset = start_offset
        for index, title in enumerate(result.titles):
            conn.execute(
                """
                INSERT OR IGNORE INTO session_titles (
                    session_id, machine_id, title, ts, path, byte_offset
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    title.session_id,
                    machine_id,
                    title.title,
                    title.ts,
                    str(file_path),
                    title_offset + index,
                ),
            )

        conn.execute(
            """
            INSERT INTO ingest_state (path, machine_id, size, mtime, byte_offset)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(path) DO UPDATE SET
                machine_id = excluded.machine_id,
                size = excluded.size,
                mtime = excluded.mtime,
                byte_offset = excluded.byte_offset
            """,
            (str(file_path), machine_id, stat.st_size, stat.st_mtime, new_offset),
        )
        if recompute:
            recompute_sessions(conn, machine_id=machine_id)

    return {
        "events": inserted_events,
        "tool_uses": inserted_tools,
        "skipped": result.skipped,
        "bytes_read": result.bytes_read,
        "unpriced": unpriced,
        "cost_usd": cost_usd,
    }


def ingest_dir(
    conn: sqlite3.Connection,
    projects_dir: str | Path,
    machine_id: str,
    prices: dict[str, dict[str, float]] | None = None,
) -> dict[str, int | float]:
    if prices is None:
        prices = load_prices()
    totals: dict[str, int | float] = {
        "files": 0,
        "events": 0,
        "tool_uses": 0,
        "skipped": 0,
        "bytes_read": 0,
        "unpriced": 0,
        "cost_usd": 0.0,
    }
    for path in sorted(Path(projects_dir).rglob("*.jsonl")):
        totals["files"] += 1
        result = ingest_file(conn, path, machine_id, prices=prices, recompute=False)
        for key in ("events", "tool_uses", "skipped", "bytes_read", "unpriced", "cost_usd"):
            totals[key] += result[key]
    # Recompute the sessions rollup once per directory rather than once per
    # file: the former O(files x sessions) pass dominated ingest at ~1k files.
    with conn:
        recompute_sessions(conn, machine_id=machine_id)
    return totals


def reprice_events(
    conn: sqlite3.Connection,
    prices: dict[str, dict[str, float]] | None = None,
) -> dict[str, int | float]:
    if prices is None:
        prices = load_prices()
    priced = 0
    unpriced = 0
    total_cost_usd = 0.0

    rows = conn.execute(
        """
        SELECT
            uuid, model, input_tokens, output_tokens, ephemeral_5m_tokens,
            ephemeral_1h_tokens, cache_read_tokens, cache_creation_tokens
        FROM events
        ORDER BY uuid
        """
    ).fetchall()
    with conn:
        for row in rows:
            event_cost_usd = cost_for(
                row["model"],
                row["input_tokens"] or 0,
                row["output_tokens"] or 0,
                row["ephemeral_5m_tokens"] or 0,
                row["ephemeral_1h_tokens"] or 0,
                row["cache_read_tokens"] or 0,
                row["cache_creation_tokens"] or 0,
                prices,
            )
            conn.execute(
                "UPDATE events SET cost_usd = ? WHERE uuid = ?",
                (event_cost_usd, row["uuid"]),
            )
            if event_cost_usd is None:
                unpriced += 1
            else:
                priced += 1
                total_cost_usd += event_cost_usd
        recompute_sessions(conn)

    return {
        "priced": priced,
        "unpriced": unpriced,
        "cost_usd": total_cost_usd,
    }
