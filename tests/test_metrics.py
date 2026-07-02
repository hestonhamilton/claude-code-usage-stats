"""Tests for the Prometheus /metrics exporter (cus.web.metrics)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from cus.config import SubscriptionConfig, SubscriptionPeriod
from cus.db import connect, init_db
from cus.ingest import ingest_dir
from cus.web import metrics as metrics_mod

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def _parse(body: str) -> dict[str, float]:
    """Parse exposition text into {series_key: value}.

    series_key is the sample line without its value, e.g.
    'cus_tokens{kind="input"}'. Comment (# HELP/# TYPE) lines are skipped.
    """
    samples: dict[str, float] = {}
    for line in body.splitlines():
        if not line or line.startswith("#"):
            continue
        key, _, value = line.rpartition(" ")
        samples[key] = float(value)
    return samples


def _build_db(tmp_path: Path, *, empty: bool = False) -> object:
    conn = connect(tmp_path / "usage.db")
    init_db(conn)
    if not empty:
        ingest_dir(conn, FIXTURE_DIR, "testbox")
    return conn


def test_none_conn_degrades_gracefully():
    body = metrics_mod.render_metrics(None)
    samples = _parse(body)
    assert samples["cus_up"] == 1
    assert samples["cus_db_available"] == 0
    # No data families are emitted when there is no DB.
    assert not any(k.startswith("cus_api_equivalent_value") for k in samples)
    # Even the degraded body is well-formed exposition.
    assert body.endswith("\n")
    assert "# TYPE cus_up gauge" in body


def test_empty_db_reports_available_but_zero_value(tmp_path):
    conn = _build_db(tmp_path, empty=True)
    try:
        samples = _parse(metrics_mod.render_metrics(conn))
    finally:
        conn.close()
    assert samples["cus_db_available"] == 1
    assert samples["cus_api_equivalent_value_usd"] == 0
    assert samples["cus_events"] == 0


def test_populated_db_emits_headline_metrics(tmp_path):
    conn = _build_db(tmp_path)
    try:
        body = metrics_mod.render_metrics(conn)
    finally:
        conn.close()
    samples = _parse(body)

    assert samples["cus_db_available"] == 1
    assert samples["cus_events"] > 0
    assert samples["cus_sessions"] > 0
    assert samples["cus_api_equivalent_value_usd"] >= 0
    # All four token kinds are present, each declared once.
    for kind in ("input", "output", "cache_creation", "cache_read"):
        assert f'cus_tokens{{kind="{kind}"}}' in samples
    assert samples["cus_last_ingest_timestamp_seconds"] > 0


def test_exposition_declares_help_and_type_once_per_family(tmp_path):
    conn = _build_db(tmp_path)
    try:
        body = metrics_mod.render_metrics(conn)
    finally:
        conn.close()
    lines = body.splitlines()
    type_decls = [ln for ln in lines if ln.startswith("# TYPE ")]
    names = [ln.split()[2] for ln in type_decls]
    # cus_tokens has 4 samples but must be declared exactly once.
    assert names.count("cus_tokens") == 1
    assert len(names) == len(set(names))
    # Every declared type in this exporter is a gauge.
    assert all(ln.endswith(" gauge") for ln in type_decls)


def test_plan_utilization_gauges(tmp_path):
    conn = _build_db(tmp_path, empty=True)
    try:
        conn.executemany(
            "INSERT INTO account_timeline (window, used_percentage, resets_at, ts)"
            " VALUES (?, ?, ?, ?)",
            [
                ("5h", 45.5, 1782910800, "2026-07-01T12:00:00Z"),
                ("5h", 82.0, 1782910800, "2026-07-01T13:00:00Z"),
                ("7d", 61.0, 1783342800, "2026-07-01T12:00:00Z"),
            ],
        )
        conn.commit()
        samples = _parse(metrics_mod.render_metrics(conn))
    finally:
        conn.close()
    # Latest 5h snapshot wins (82.0, not the earlier 45.5).
    assert samples['cus_plan_used_percentage{window="5h"}'] == 82.0
    assert samples['cus_plan_used_percentage{window="7d"}'] == 61.0
    assert samples['cus_plan_resets_at_seconds{window="5h"}'] == 1782910800


def test_subscription_roi_metrics(tmp_path):
    conn = _build_db(tmp_path)
    subscription = SubscriptionConfig(
        periods=(
            SubscriptionPeriod(
                monthly_usd=100.0, started_on=date(2026, 1, 1), plan="max5"
            ),
        )
    )
    try:
        samples = _parse(metrics_mod.render_metrics(conn, subscription))
    finally:
        conn.close()
    assert samples["cus_subscription_cost_usd"] > 0
    assert "cus_subscription_roi_ratio" in samples
    assert samples["cus_subscription_billing_cycles"] >= 1


def test_no_subscription_omits_roi(tmp_path):
    conn = _build_db(tmp_path)
    try:
        samples = _parse(metrics_mod.render_metrics(conn, None))
    finally:
        conn.close()
    assert not any(k.startswith("cus_subscription_") for k in samples)


@pytest.mark.parametrize(
    "value,expected",
    [
        (0, "0"),
        (42, "42"),
        (True, "1"),
        (False, "0"),
        (1234.56, "1234.56"),
        (0.10000000001, "0.1"),
        (float("nan"), "NaN"),
        (float("inf"), "+Inf"),
    ],
)
def test_fmt(value, expected):
    assert metrics_mod._fmt(value) == expected


def test_iso_to_epoch():
    assert metrics_mod._iso_to_epoch(None) is None
    assert metrics_mod._iso_to_epoch("not-a-date") is None
    # Naive stamp is assumed UTC.
    assert metrics_mod._iso_to_epoch("2026-07-01T00:00:00") == pytest.approx(
        1782864000, abs=1
    )
    assert metrics_mod._iso_to_epoch("2026-07-01T00:00:00+00:00") == pytest.approx(
        1782864000, abs=1
    )


def test_label_escaping():
    exp = metrics_mod._Exposition()
    exp.gauge("cus_x", "help", 1, labels={"k": 'a"b\\c'})
    assert 'cus_x{k="a\\"b\\\\c"} 1' in exp.render()
