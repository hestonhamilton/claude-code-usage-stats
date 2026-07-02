from datetime import date

from cus.config import SubscriptionPeriod
from cus.db import connect, init_db
from cus.rollups import _billing_cycles, overview, subscription_roi


def _seed_events(conn):
    conn.executemany(
        "INSERT INTO events (uuid, ts, cost_usd) VALUES (?, ?, ?)",
        [
            ("e1", "2026-04-05T00:00:00Z", 10.0),
            ("e2", "2026-06-10T00:00:00Z", 20.0),
            ("e3", "2026-06-20T00:00:00Z", 5.0),
        ],
    )
    conn.commit()


def _period(monthly, start, end=None, plan=None):
    return SubscriptionPeriod(monthly_usd=monthly, started_on=start, ended_on=end, plan=plan)


def test_billing_cycles_counts_anniversaries_not_calendar_months():
    # A plan started on the 29th running ~5 weeks bills TWICE (29th, 29th),
    # even though it touches three calendar months. This is the M2 fix.
    anchor = date(2026, 5, 29)
    assert _billing_cycles(anchor, anchor, date(2026, 7, 2)) == 2
    # One day before the second anniversary -> only one charge.
    assert _billing_cycles(anchor, anchor, date(2026, 6, 28)) == 1
    # Empty / inverted window -> zero.
    assert _billing_cycles(anchor, date(2026, 6, 1), date(2026, 5, 1)) == 0


def test_billing_cycles_clamps_overflow_day():
    # Jan 31 anniversaries land on the last day of short months.
    anchor = date(2026, 1, 31)
    # Jan 31, Feb 28, Mar 31 -> 3 charges through end of March.
    assert _billing_cycles(anchor, anchor, date(2026, 3, 31)) == 3


def test_subscription_roi_multi_period_lifetime(tmp_path):
    conn = connect(tmp_path / "usage.db")
    try:
        init_db(conn)
        _seed_events(conn)
        # Real scenario: Pro Mar 24 -> May 29 (closed), then Max5 May 29 ->
        # ongoing, evaluated as of 2026-07-02 (explicit end_day for a
        # clock-independent test). Anniversaries: Pro = Mar24, Apr24, May24 (3);
        # Max5 = May29, Jun29 (2) -> "paid twice".
        periods = [
            _period(20.0, date(2026, 3, 24), date(2026, 5, 29), "pro"),
            _period(100.00, date(2026, 5, 29), None, "max5"),
        ]
        result = subscription_roi(conn, periods, end_day="2026-07-02")

        api_value = overview(conn, end_day="2026-07-02")["cost_usd"]
        assert result["api_value_usd"] == api_value == 35.0
        # 3 * 20 + 2 * 100.00 = 60 + 200.00
        assert result["cycles"] == 5
        assert round(result["subscription_usd"], 2) == 260.00
        assert result["ratio"] == 35.0 / result["subscription_usd"]
        # Per-period breakdown is exposed for display.
        assert [p["cycles"] for p in result["periods"]] == [3, 2]
        assert result["periods"][1]["plan"] == "max5"
    finally:
        conn.close()


def test_subscription_roi_ongoing_period_uses_today(tmp_path):
    conn = connect(tmp_path / "usage.db")
    try:
        init_db(conn)
        _seed_events(conn)
        # Started on the 1st of this month, ongoing: at least the first charge
        # has landed. Kept loose to stay deterministic across run dates.
        today = date.today()
        start = date(today.year, today.month, 1)
        result = subscription_roi(conn, [_period(100.0, start)])
        assert result["cycles"] >= 1
        assert result["subscription_usd"] >= 100.0
    finally:
        conn.close()


def test_subscription_roi_clips_cost_and_value_to_date_range(tmp_path):
    conn = connect(tmp_path / "usage.db")
    try:
        init_db(conn)
        _seed_events(conn)
        # Requesting only June: value = 25.0 (e2+e3); the period's single
        # anniversary in June (Jun 24) counts once.
        periods = [_period(100.0, date(2026, 4, 24), date(2026, 8, 2))]
        result = subscription_roi(conn, periods, start_day="2026-06-01", end_day="2026-06-30")
        assert result["api_value_usd"] == 25.0
        assert result["cycles"] == 1
        assert result["subscription_usd"] == 100.0
    finally:
        conn.close()


def test_subscription_roi_none_when_no_periods(tmp_path):
    conn = connect(tmp_path / "usage.db")
    try:
        init_db(conn)
        assert subscription_roi(conn, None) is None
        assert subscription_roi(conn, []) is None
    finally:
        conn.close()


def test_subscription_roi_ratio_guarded_when_zero_cost(tmp_path):
    conn = connect(tmp_path / "usage.db")
    try:
        init_db(conn)
        _seed_events(conn)
        # Period entirely outside the requested range -> zero charges, no
        # divide-by-zero.
        periods = [_period(100.0, date(2026, 9, 1), date(2026, 10, 1))]
        result = subscription_roi(conn, periods, start_day="2026-01-01", end_day="2026-06-30")
        assert result["subscription_usd"] == 0.0
        assert result["ratio"] is None
    finally:
        conn.close()
