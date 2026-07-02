from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


RatelimitRow = tuple[str, float, int, str]


@dataclass(frozen=True)
class RatelimitParseResult:
    rows: list[RatelimitRow]
    skipped: int


def _as_number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    return None


def _as_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def _as_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _parse_window(
    rate_limits: dict[str, object],
    source_key: str,
    window: str,
    ts: str,
) -> RatelimitRow | None:
    data = rate_limits.get(source_key)
    if data is None:
        return None
    if not isinstance(data, dict):
        return None
    used_percentage = _as_number(data.get("used_percentage"))
    resets_at = _as_int(data.get("resets_at"))
    if used_percentage is None or resets_at is None:
        return None
    return (window, used_percentage, resets_at, ts)


def parse_ratelimit_lines(iterable_of_str: Iterable[str]) -> RatelimitParseResult:
    rows: list[RatelimitRow] = []
    skipped = 0

    for line in iterable_of_str:
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            skipped += 1
            continue
        if not isinstance(record, dict):
            skipped += 1
            continue

        ts = _as_str(record.get("ts"))
        rate_limits = record.get("rate_limits")
        if rate_limits is None:
            rate_limits = {
                "five_hour": {
                    "used_percentage": record.get("five_hour_pct"),
                    "resets_at": record.get("five_hour_resets_at"),
                },
                "seven_day": {
                    "used_percentage": record.get("seven_day_pct"),
                    "resets_at": record.get("seven_day_resets_at"),
                },
            }
        if not ts or not isinstance(rate_limits, dict):
            skipped += 1
            continue

        parsed = [
            _parse_window(rate_limits, "five_hour", "5h", ts),
            _parse_window(rate_limits, "seven_day", "7d", ts),
        ]
        valid = [row for row in parsed if row is not None]
        if not valid:
            skipped += 1
            continue
        rows.extend(valid)

    return RatelimitParseResult(rows=rows, skipped=skipped)


def ingest_ratelimits_file(conn: sqlite3.Connection, path: str | Path) -> dict[str, int]:
    file_path = Path(path)
    with file_path.open("r", encoding="utf-8", errors="replace") as handle:
        result = parse_ratelimit_lines(handle)

    inserted = 0
    with conn:
        for window, used_percentage, resets_at, ts in result.rows:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO account_timeline (
                    window, used_percentage, resets_at, ts
                ) VALUES (?, ?, ?, ?)
                """,
                (window, used_percentage, resets_at, ts),
            )
            if cursor.rowcount == 1:
                inserted += 1

    return {"inserted": inserted, "skipped": result.skipped}
