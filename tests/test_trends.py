import math
import sqlite3
from pathlib import Path

import pytest

from cus import rollups
from cus.db import connect, init_db


def _conn(tmp_path: Path) -> sqlite3.Connection:
    conn = connect(tmp_path / "usage.db")
    init_db(conn)
    return conn


def _insert(conn: sqlite3.Connection, rows: list[dict]) -> None:
    for i, row in enumerate(rows):
        row.setdefault("uuid", f"e{i}-{row['ts']}")
        columns = ", ".join(row)
        placeholders = ", ".join("?" for _ in row)
        conn.execute(
            f"INSERT INTO events ({columns}) VALUES ({placeholders})",
            list(row.values()),
        )
    conn.commit()


# --- by_week -----------------------------------------------------------

def test_by_week_buckets_by_monday_and_computes_wow_pct_change(tmp_path):
    conn = _conn(tmp_path)
    try:
        # Week of 2026-06-01 (Mon) = $20, week of 2026-06-08 (Mon) = $30,
        # week of 2026-06-15 (Mon) = $0 (all unpriced), week of 2026-06-22 = $15.
        _insert(
            conn,
            [
                {"ts": "2026-06-01T00:00:00Z", "cost_usd": 10.0},
                {"ts": "2026-06-03T00:00:00Z", "cost_usd": 10.0},
                {"ts": "2026-06-08T00:00:00Z", "cost_usd": 30.0},
                {"ts": "2026-06-15T00:00:00Z", "cost_usd": None},
                {"ts": "2026-06-22T00:00:00Z", "cost_usd": 15.0},
            ],
        )
        weeks = rollups.by_week(conn)
    finally:
        conn.close()

    assert [w["week"] for w in weeks] == [
        "2026-06-01",
        "2026-06-08",
        "2026-06-15",
        "2026-06-22",
    ]
    assert [w["cost_usd"] for w in weeks] == [20.0, 30.0, 0.0, 15.0]
    assert [w["events"] for w in weeks] == [2, 1, 1, 1]

    # First week: no prior baseline.
    assert weeks[0]["wow_pct_change"] is None
    # 20 -> 30: +50%.
    assert math.isclose(weeks[1]["wow_pct_change"], 0.5)
    # 30 -> 0: -100%.
    assert math.isclose(weeks[2]["wow_pct_change"], -1.0)
    # 0 -> 15: no baseline to compute a ratio from (avoid div-by-zero) -> None.
    assert weeks[3]["wow_pct_change"] is None


def test_by_week_respects_filters(tmp_path):
    conn = _conn(tmp_path)
    try:
        _insert(
            conn,
            [
                {"ts": "2026-06-01T00:00:00Z", "cost_usd": 10.0, "machine_id": "a"},
                {"ts": "2026-06-01T00:00:00Z", "cost_usd": 5.0, "machine_id": "b"},
            ],
        )
        weeks = rollups.by_week(conn, machine="a")
    finally:
        conn.close()

    assert len(weeks) == 1
    assert weeks[0]["cost_usd"] == 10.0


# --- cost_trend ----------------------------------------------------------

def test_cost_trend_moving_average_grows_then_slides(tmp_path):
    conn = _conn(tmp_path)
    try:
        _insert(
            conn,
            [
                {"ts": "2026-06-01T00:00:00Z", "cost_usd": 10.0},
                {"ts": "2026-06-02T00:00:00Z", "cost_usd": 20.0},
                {"ts": "2026-06-03T00:00:00Z", "cost_usd": 30.0},
                {"ts": "2026-06-04T00:00:00Z", "cost_usd": 40.0},
                {"ts": "2026-06-05T00:00:00Z", "cost_usd": 50.0},
            ],
        )
        trend = rollups.cost_trend(conn, window=3)
    finally:
        conn.close()

    assert [row["cost_usd"] for row in trend] == [10.0, 20.0, 30.0, 40.0, 50.0]
    # day1: avg(10); day2: avg(10,20); day3+: trailing 3-day window.
    expected_ma = [10.0, 15.0, 20.0, 30.0, 40.0]
    for row, expected in zip(trend, expected_ma):
        assert math.isclose(row["cost_ma"], expected)


def test_cost_trend_empty_range_returns_empty_list(tmp_path):
    conn = _conn(tmp_path)
    try:
        trend = rollups.cost_trend(conn)
    finally:
        conn.close()
    assert trend == []


# --- cache_efficiency_timeline --------------------------------------------

def test_cache_efficiency_timeline_matches_hand_computed_discount(tmp_path):
    conn = _conn(tmp_path)
    try:
        _insert(
            conn,
            [
                {
                    "ts": "2026-06-01T00:00:00Z",
                    "model": "claude-opus-4-8",
                    "cache_read_tokens": 100,
                    "cost_usd": 1.0,
                },
                {
                    "ts": "2026-06-08T00:00:00Z",
                    "model": "claude-opus-4-8",
                    "cache_read_tokens": 200,
                    "cost_usd": 2.0,
                },
            ],
        )
        timeline = rollups.cache_efficiency_timeline(conn, by="week")
        totals = rollups.cache_savings(conn)
    finally:
        conn.close()

    input_rate = 5 / 1_000_000
    week1_saved = 100 * input_rate * 0.90
    week2_saved = 200 * input_rate * 0.90

    assert [row["week"] for row in timeline] == ["2026-06-01", "2026-06-08"]
    assert math.isclose(timeline[0]["saved_usd"], week1_saved)
    assert math.isclose(
        timeline[0]["effective_discount_pct"], week1_saved / (1.0 + week1_saved)
    )
    assert math.isclose(timeline[1]["saved_usd"], week2_saved)
    assert math.isclose(
        timeline[1]["effective_discount_pct"], week2_saved / (2.0 + week2_saved)
    )

    # Cross-check: summing every bucket reproduces cache_savings' totals for
    # the same (unfiltered) range exactly.
    assert timeline[0]["cache_read_tokens"] + timeline[1]["cache_read_tokens"] == (
        totals["cache_read_tokens"]
    )
    assert math.isclose(
        timeline[0]["cost_usd"] + timeline[1]["cost_usd"], totals["cost_usd"]
    )
    assert math.isclose(
        timeline[0]["saved_usd"] + timeline[1]["saved_usd"], totals["saved_usd"]
    )


def test_cache_efficiency_timeline_by_day(tmp_path):
    conn = _conn(tmp_path)
    try:
        _insert(
            conn,
            [
                {
                    "ts": "2026-06-01T00:00:00Z",
                    "model": "claude-opus-4-8",
                    "cache_read_tokens": 100,
                    "cost_usd": 1.0,
                },
            ],
        )
        timeline = rollups.cache_efficiency_timeline(conn, by="day")
    finally:
        conn.close()

    assert [row["day"] for row in timeline] == ["2026-06-01"]


def test_cache_efficiency_timeline_rejects_bad_by(tmp_path):
    conn = _conn(tmp_path)
    try:
        with pytest.raises(ValueError):
            rollups.cache_efficiency_timeline(conn, by="month")
    finally:
        conn.close()


def test_cache_efficiency_timeline_skips_unpriced_models(tmp_path):
    conn = _conn(tmp_path)
    try:
        _insert(
            conn,
            [
                {
                    "ts": "2026-06-01T00:00:00Z",
                    "model": "totally-unknown-model",
                    "cache_read_tokens": 100,
                    "cost_usd": None,
                },
            ],
        )
        timeline = rollups.cache_efficiency_timeline(conn)
    finally:
        conn.close()

    # The bucket still appears (so the timeline has no gaps for days that saw
    # activity) but with zeroed cache stats: an unresolvable rate is skipped
    # from the accumulators exactly like `cache_savings`' own `continue`.
    assert timeline == [
        {
            "week": "2026-06-01",
            "cache_read_tokens": 0,
            "cost_usd": 0.0,
            "saved_usd": 0.0,
            "effective_discount_pct": 0.0,
        }
    ]


# --- model_mix_timeline ----------------------------------------------------

def test_model_mix_timeline_top_n_and_other_rollup(tmp_path):
    conn = _conn(tmp_path)
    try:
        _insert(
            conn,
            [
                {"ts": "2026-06-01T00:00:00Z", "model": "A", "cost_usd": 60.0},
                {"ts": "2026-06-01T00:00:00Z", "model": "B", "cost_usd": 30.0},
                {"ts": "2026-06-01T00:00:00Z", "model": "C", "cost_usd": 6.0},
                {"ts": "2026-06-01T00:00:00Z", "model": "D", "cost_usd": 3.0},
                {"ts": "2026-06-08T00:00:00Z", "model": "A", "cost_usd": 40.0},
                {"ts": "2026-06-08T00:00:00Z", "model": "B", "cost_usd": 20.0},
                {"ts": "2026-06-08T00:00:00Z", "model": "C", "cost_usd": 4.0},
                {"ts": "2026-06-08T00:00:00Z", "model": "D", "cost_usd": 2.0},
            ],
        )
        # Totals: A=100, B=50, C=10, D=5 -> top 2 = [A, B]; C+D -> <other>.
        result = rollups.model_mix_timeline(conn, by="week", top=2)
    finally:
        conn.close()

    assert result["top_models"] == ["A", "B", "<other>"]
    periods = result["periods"]
    assert [p["week"] for p in periods] == ["2026-06-01", "2026-06-08"]

    assert math.isclose(periods[0]["cost_usd"], 99.0)
    assert periods[0]["models"] == {"A": 60.0, "B": 30.0, "<other>": 9.0}

    assert math.isclose(periods[1]["cost_usd"], 66.0)
    assert periods[1]["models"] == {"A": 40.0, "B": 20.0, "<other>": 6.0}


def test_model_mix_timeline_no_other_when_models_fit(tmp_path):
    conn = _conn(tmp_path)
    try:
        _insert(
            conn,
            [
                {"ts": "2026-06-01T00:00:00Z", "model": "A", "cost_usd": 10.0},
                {"ts": "2026-06-01T00:00:00Z", "model": "B", "cost_usd": 5.0},
            ],
        )
        result = rollups.model_mix_timeline(conn, by="week", top=6)
    finally:
        conn.close()

    assert result["top_models"] == ["A", "B"]
    assert result["periods"][0]["models"] == {"A": 10.0, "B": 5.0}


def test_model_mix_timeline_null_model_becomes_unknown_bucket(tmp_path):
    conn = _conn(tmp_path)
    try:
        _insert(conn, [{"ts": "2026-06-01T00:00:00Z", "model": None, "cost_usd": 1.0}])
        result = rollups.model_mix_timeline(conn, by="week", top=6)
    finally:
        conn.close()

    assert result["top_models"] == ["<unknown>"]
    assert result["periods"][0]["models"] == {"<unknown>": 1.0}


def test_model_mix_timeline_empty_db_returns_no_periods(tmp_path):
    conn = _conn(tmp_path)
    try:
        result = rollups.model_mix_timeline(conn)
    finally:
        conn.close()

    assert result == {"top_models": [], "periods": []}
