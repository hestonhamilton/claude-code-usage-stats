import json

from cus.db import connect, init_db
from cus.ratelimits import ingest_ratelimits_file, parse_ratelimit_lines
from cus.rollups import WINDOW_FULL_PCT, plan_status, plan_timeline, value_realized


def test_parse_ratelimit_line_with_both_windows():
    result = parse_ratelimit_lines(
        [
            json.dumps(
                {
                    "ts": "2026-07-01T12:00:00Z",
                    "five_hour_pct": 42.5,
                    "five_hour_resets_at": 1782910800,
                    "seven_day_pct": 63,
                    "seven_day_resets_at": 1783342800,
                }
            )
        ]
    )

    assert result.skipped == 0
    assert result.rows == [
        ("5h", 42.5, 1782910800, "2026-07-01T12:00:00Z"),
        ("7d", 63.0, 1783342800, "2026-07-01T12:00:00Z"),
    ]


def test_parse_ratelimit_skips_null_and_malformed_lines():
    result = parse_ratelimit_lines(
        [
            json.dumps({"ts": "2026-07-01T12:00:00Z", "rate_limits": None}),
            "{not-json",
        ]
    )

    assert result.rows == []
    assert result.skipped == 2


def test_account_timeline_ingest_dedups_identical_snapshots(tmp_path):
    log_path = tmp_path / "rate-limits.jsonl"
    snapshot = {
        "ts": "2026-07-01T12:00:00Z",
        "five_hour_pct": 20,
        "five_hour_resets_at": 1782910800,
        "seven_day_pct": 40,
        "seven_day_resets_at": 1783342800,
    }
    log_path.write_text(json.dumps(snapshot) + "\n", encoding="utf-8")

    conn = connect(tmp_path / "usage.db")
    try:
        init_db(conn)
        first = ingest_ratelimits_file(conn, log_path)
        second = ingest_ratelimits_file(conn, log_path)
        count = conn.execute("SELECT COUNT(*) FROM account_timeline").fetchone()[0]

        assert first == {"inserted": 2, "skipped": 0}
        assert second == {"inserted": 0, "skipped": 0}
        assert count == 2
    finally:
        conn.close()


def test_account_timeline_ingest_keeps_different_snapshots(tmp_path):
    log_path = tmp_path / "rate-limits.jsonl"
    log_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "ts": "2026-07-01T12:00:00Z",
                        "five_hour_pct": 20,
                        "five_hour_resets_at": 1782910800,
                    }
                ),
                json.dumps(
                    {
                        "ts": "2026-07-01T12:05:00Z",
                        "five_hour_pct": 21,
                        "five_hour_resets_at": 1782910800,
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    conn = connect(tmp_path / "usage.db")
    try:
        init_db(conn)
        result = ingest_ratelimits_file(conn, log_path)
        timeline = plan_timeline(conn, "5h")

        assert result == {"inserted": 2, "skipped": 0}
        assert [row["used_percentage"] for row in timeline] == [20.0, 21.0]
    finally:
        conn.close()


def test_plan_status_returns_latest_per_window(tmp_path):
    conn = connect(tmp_path / "usage.db")
    try:
        init_db(conn)
        conn.executemany(
            """
            INSERT INTO account_timeline (window, used_percentage, resets_at, ts)
            VALUES (?, ?, ?, ?)
            """,
            [
                ("5h", 20.0, 1782910800, "2026-07-01T12:00:00Z"),
                ("5h", 25.0, 1782910800, "2026-07-01T12:10:00Z"),
                ("7d", 40.0, 1783342800, "2026-07-01T12:03:00Z"),
                ("7d", 41.0, 1783342800, "2026-07-01T12:11:00Z"),
            ],
        )

        status = plan_status(conn)

        assert status["5h"]["used_percentage"] == 25.0
        assert status["7d"]["used_percentage"] == 41.0
    finally:
        conn.close()


def _seed_value_realized_fixture(conn):
    # 5h: two reset windows.
    #   resets_at=100 (day 07-01): 50.0, 96.0  -> peak 96.0, "realized" (>= WINDOW_FULL_PCT)
    #   resets_at=200 (day 07-01): 80.0         -> peak 80.0, not realized
    #   resets_at=300 (day 07-02): 99.0         -> peak 99.0, realized (outside the day filter used below)
    # 7d: one reset window, not realized.
    conn.executemany(
        """
        INSERT INTO account_timeline (window, used_percentage, resets_at, ts)
        VALUES (?, ?, ?, ?)
        """,
        [
            ("5h", 50.0, 100, "2026-07-01T10:00:00Z"),
            ("5h", 96.0, 100, "2026-07-01T11:00:00Z"),
            ("5h", 80.0, 200, "2026-07-01T12:00:00Z"),
            ("5h", 99.0, 300, "2026-07-02T09:00:00Z"),
            ("7d", 61.0, 900, "2026-07-01T12:00:00Z"),
        ],
    )
    conn.commit()


def test_value_realized_computes_peak_avg_and_realized_windows(tmp_path):
    conn = connect(tmp_path / "usage.db")
    try:
        init_db(conn)
        _seed_value_realized_fixture(conn)

        result = value_realized(conn)

        assert WINDOW_FULL_PCT == 95
        assert result["5h"]["peak_pct"] == 99.0
        assert result["5h"]["avg_pct"] == (50.0 + 96.0 + 80.0 + 99.0) / 4
        assert result["5h"]["windows_total"] == 3
        assert result["5h"]["windows_realized"] == 2  # resets_at 100 and 300

        assert result["7d"]["peak_pct"] == 61.0
        assert result["7d"]["avg_pct"] == 61.0
        assert result["7d"]["windows_total"] == 1
        assert result["7d"]["windows_realized"] == 0
    finally:
        conn.close()


def test_value_realized_respects_date_range_filter(tmp_path):
    conn = connect(tmp_path / "usage.db")
    try:
        init_db(conn)
        _seed_value_realized_fixture(conn)

        # Excludes resets_at=300 (2026-07-02).
        result = value_realized(conn, start_day="2026-07-01", end_day="2026-07-01")

        assert result["5h"]["peak_pct"] == 96.0
        assert result["5h"]["avg_pct"] == (50.0 + 96.0 + 80.0) / 3
        assert result["5h"]["windows_total"] == 2
        assert result["5h"]["windows_realized"] == 1  # only resets_at 100
    finally:
        conn.close()


def test_value_realized_none_safe_on_empty_table(tmp_path):
    conn = connect(tmp_path / "usage.db")
    try:
        init_db(conn)

        result = value_realized(conn)

        assert result == {
            "5h": {"peak_pct": None, "avg_pct": None, "windows_realized": 0, "windows_total": 0},
            "7d": {"peak_pct": None, "avg_pct": None, "windows_realized": 0, "windows_total": 0},
        }
    finally:
        conn.close()


def test_value_realized_ignores_machine_kwarg(tmp_path):
    # account_timeline has no machine_id column (single shared account); the
    # `machine` kwarg exists only for filter-signature parity and must not
    # change or break the result.
    conn = connect(tmp_path / "usage.db")
    try:
        init_db(conn)
        _seed_value_realized_fixture(conn)

        with_machine = value_realized(conn, machine="some-box")
        without_machine = value_realized(conn)

        assert with_machine == without_machine
    finally:
        conn.close()
