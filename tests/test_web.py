import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx2")  # starlette TestClient's HTTP client in this env
from fastapi.testclient import TestClient

try:
    _testclient_probe = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from fastapi import FastAPI;"
                "from fastapi.testclient import TestClient;"
                "app=FastAPI();"
                "app.get('/healthz')(lambda: {'ok': True});"
                "raise SystemExit(0 if TestClient(app).get('/healthz').status_code == 200 else 1)"
            ),
        ],
        timeout=5,
        check=False,
    )
    _testclient_returncode = _testclient_probe.returncode
except subprocess.TimeoutExpired:
    _testclient_returncode = 1
if _testclient_returncode != 0:
    pytest.skip("fastapi TestClient is not functional in this environment", allow_module_level=True)

from cus.db import connect, init_db
from cus.ingest import ingest_dir
from cus.web.app import app


FIXTURE_DIR = Path(__file__).parent / "fixtures"


def _build_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "usage.db"
    conn = connect(db_path)
    try:
        init_db(conn)
        ingest_dir(conn, FIXTURE_DIR, "testbox")
    finally:
        conn.close()
    return db_path


def _build_empty_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "empty.db"
    conn = connect(db_path)
    try:
        init_db(conn)
    finally:
        conn.close()
    return db_path


def _build_plan_db(tmp_path: Path, *, with_data: bool) -> Path:
    db_path = tmp_path / "plan.db"
    conn = connect(db_path)
    try:
        init_db(conn)
        if with_data:
            conn.executemany(
                """
                INSERT INTO account_timeline (window, used_percentage, resets_at, ts)
                VALUES (?, ?, ?, ?)
                """,
                [
                    ("5h", 45.5, 1782910800, "2026-07-01T12:00:00Z"),
                    ("7d", 61.0, 1783342800, "2026-07-01T12:00:00Z"),
                ],
            )
            conn.commit()
    finally:
        conn.close()
    return db_path


def _build_db_with_plan(tmp_path: Path) -> Path:
    """Fixture events (dated 2026-06-16) plus account_timeline snapshots for
    the same day, so a June date filter exercises both Metric A and B
    end-to-end in one request."""
    db_path = tmp_path / "usage_with_plan.db"
    conn = connect(db_path)
    try:
        init_db(conn)
        ingest_dir(conn, FIXTURE_DIR, "testbox")
        conn.executemany(
            """
            INSERT INTO account_timeline (window, used_percentage, resets_at, ts)
            VALUES (?, ?, ?, ?)
            """,
            [
                ("5h", 45.5, 1782910800, "2026-06-16T10:00:00Z"),
                ("5h", 96.0, 1782910800, "2026-06-16T11:00:00Z"),
                ("7d", 61.0, 1783342800, "2026-06-16T12:00:00Z"),
            ],
        )
        conn.commit()
    finally:
        conn.close()
    return db_path


def _write_subscription_config(tmp_path: Path) -> Path:
    config_path = tmp_path / "subscription-machines.toml"
    config_path.write_text(
        """
[central]
db_path = "./data/cus.db"
staging_dir = "./staging"

[[machines]]
id = "testbox"
transport = "local"
path = "/tmp/does-not-matter"

[[subscription.periods]]
plan = "max5"
monthly_usd = 100.0
started_on = 2026-01-01
""",
        encoding="utf-8",
    )
    return config_path


def test_healthz(monkeypatch, tmp_path):
    db_path = _build_db(tmp_path)
    monkeypatch.setenv("CUS_DB", str(db_path))

    client = TestClient(app)

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_dashboard_contains_fixture_title_and_cost(monkeypatch, tmp_path):
    db_path = _build_db(tmp_path)
    monkeypatch.setenv("CUS_DB", str(db_path))

    client = TestClient(app)

    response = client.get("/")

    assert response.status_code == 200
    assert "Final title" in response.text
    assert "API-equivalent value" in response.text
    assert "Estimated pay-per-token API cost of this usage" in response.text
    assert "$0.00" in response.text


def test_sessions_lists_fixture_session(monkeypatch, tmp_path):
    db_path = _build_db(tmp_path)
    monkeypatch.setenv("CUS_DB", str(db_path))

    client = TestClient(app)

    response = client.get("/sessions")

    assert response.status_code == 200
    assert "session-1" in response.text


def test_session_detail_and_missing_session(monkeypatch, tmp_path):
    db_path = _build_db(tmp_path)
    monkeypatch.setenv("CUS_DB", str(db_path))

    client = TestClient(app)

    response = client.get("/session/session-1")
    missing = client.get("/session/does-not-exist")

    assert response.status_code == 200
    assert "Final title" in response.text
    assert "claude-opus-4-8" in response.text
    assert missing.status_code == 404


def test_dashboard_accepts_empty_start_end_query_params(monkeypatch, tmp_path):
    # htmx submits start=&end= for an unset date filter; that must not 422.
    db_path = _build_db(tmp_path)
    monkeypatch.setenv("CUS_DB", str(db_path))

    client = TestClient(app)

    response = client.get("/", params={"start": "", "end": ""})

    assert response.status_code == 200


def test_breakdowns_partial_accepts_empty_start_end_query_params(monkeypatch, tmp_path):
    db_path = _build_db(tmp_path)
    monkeypatch.setenv("CUS_DB", str(db_path))

    client = TestClient(app)

    response = client.get("/partials/breakdowns", params={"start": "", "end": ""})

    assert response.status_code == 200


def test_missing_db_dashboard_returns_empty_state(monkeypatch, tmp_path):
    missing_path = tmp_path / "missing.db"
    monkeypatch.setenv("CUS_DB", str(missing_path))

    client = TestClient(app)

    response = client.get("/")

    assert response.status_code == 200
    assert "No database found" in response.text


def test_highlights_contains_fixture_insights(monkeypatch, tmp_path):
    db_path = _build_db(tmp_path)
    monkeypatch.setenv("CUS_DB", str(db_path))

    client = TestClient(app)

    response = client.get("/highlights")

    assert response.status_code == 200
    assert "Caching saved you" in response.text
    assert "API-equivalent value by project" in response.text
    assert "Estimated pay-per-token API cost of this usage" in response.text
    assert "$0.00" in response.text
    assert "/work/project-one" in response.text
    assert "main" in response.text


def test_highlights_missing_and_empty_db_return_empty_states(monkeypatch, tmp_path):
    client = TestClient(app)

    missing_path = tmp_path / "missing.db"
    monkeypatch.setenv("CUS_DB", str(missing_path))
    missing = client.get("/highlights")

    empty_path = _build_empty_db(tmp_path)
    monkeypatch.setenv("CUS_DB", str(empty_path))
    empty = client.get("/highlights")

    assert missing.status_code == 200
    assert "No database found" in missing.text
    assert empty.status_code == 200
    assert "No highlights yet" in empty.text


def test_plan_returns_data(monkeypatch, tmp_path):
    db_path = _build_plan_db(tmp_path, with_data=True)
    monkeypatch.setenv("CUS_DB", str(db_path))

    client = TestClient(app)

    response = client.get("/plan")

    assert response.status_code == 200
    assert "Five hour" in response.text
    assert "45.5%" in response.text
    assert "Seven day" in response.text
    assert "61.0%" in response.text


def test_plan_returns_empty_state(monkeypatch, tmp_path):
    db_path = _build_plan_db(tmp_path, with_data=False)
    monkeypatch.setenv("CUS_DB", str(db_path))

    client = TestClient(app)

    response = client.get("/plan")

    assert response.status_code == 200
    assert "No plan snapshots yet" in response.text


def test_dashboard_shows_plan_nudge_and_hides_roi_without_data_or_config(monkeypatch, tmp_path):
    db_path = _build_db(tmp_path)
    monkeypatch.setenv("CUS_DB", str(db_path))
    # Explicit missing path: must not depend on any local config/machines.toml.
    monkeypatch.setenv("CUS_CONFIG", str(tmp_path / "missing-config.toml"))

    client = TestClient(app)

    response = client.get("/")

    assert response.status_code == 200
    assert "Value Realized" in response.text
    assert "No plan snapshots yet. Wire" in response.text
    assert "scripts/setup-statusline.sh" in response.text
    assert "roi-line" not in response.text


def test_dashboard_shows_gauges_and_roi_with_data_and_config(monkeypatch, tmp_path):
    db_path = _build_db_with_plan(tmp_path)
    monkeypatch.setenv("CUS_DB", str(db_path))
    config_path = _write_subscription_config(tmp_path)
    monkeypatch.setenv("CUS_CONFIG", str(config_path))

    client = TestClient(app)

    response = client.get("/", params={"start": "2026-06-01", "end": "2026-06-30"})

    assert response.status_code == 200
    # Current gauges (latest snapshot per window, from plan_status).
    assert "96.0%" in response.text
    assert "61.0%" in response.text
    # Period summary (value_realized): 5h window fully used once, 7d never.
    text = " ".join(response.text.split())
    assert "Fully used 1 of 1 five hour windows this period" in text
    assert "Fully used 0 of 1 seven day windows this period" in text
    # ROI line: subscription started 2026-01-01, filtered range is all of
    # June 2026 -> 1 overlapping month -> $100 paid; the fixture's tiny
    # API-equivalent cost rounds to a 0.0x return but must still render
    # without dividing by zero.
    assert "roi-line" in response.text
    assert "~$100.00 paid" in response.text
    assert "0.0x</strong> return" in response.text


def test_trends_contains_fixture_insights(monkeypatch, tmp_path):
    db_path = _build_db(tmp_path)
    monkeypatch.setenv("CUS_DB", str(db_path))

    client = TestClient(app)

    response = client.get("/trends")

    assert response.status_code == 200
    assert "Daily Cost" in response.text
    assert "Weekly Cost" in response.text
    assert "Cache Efficiency Over Time" in response.text
    assert "Model Mix Over Time" in response.text
    assert "claude-opus-4-8" in response.text
    # Both fixture events are 2026-06-16 (a Tuesday) -> ISO week of 2026-06-15.
    assert "2026-06-15" in response.text
    # Deferred burn-rate/forecast pointer.
    text = " ".join(response.text.split())
    assert "coming once plan snapshots are captured" in text
    assert '<a href="/plan">Plan</a>' in text


def test_trends_nav_link_present(monkeypatch, tmp_path):
    db_path = _build_db(tmp_path)
    monkeypatch.setenv("CUS_DB", str(db_path))

    client = TestClient(app)

    response = client.get("/")

    assert '<a href="/trends">Trends</a>' in response.text


def test_trends_missing_and_empty_db_return_empty_states(monkeypatch, tmp_path):
    client = TestClient(app)

    missing_path = tmp_path / "missing.db"
    monkeypatch.setenv("CUS_DB", str(missing_path))
    missing = client.get("/trends")

    empty_path = _build_empty_db(tmp_path)
    monkeypatch.setenv("CUS_DB", str(empty_path))
    empty = client.get("/trends")

    assert missing.status_code == 200
    assert "No database found" in missing.text
    assert empty.status_code == 200
    assert "No trend data yet" in empty.text


def test_trends_accepts_empty_start_end_query_params(monkeypatch, tmp_path):
    db_path = _build_db(tmp_path)
    monkeypatch.setenv("CUS_DB", str(db_path))

    client = TestClient(app)

    response = client.get("/trends", params={"start": "", "end": ""})

    assert response.status_code == 200


def test_dashboard_empty_db_shows_plan_nudge_without_crashing(monkeypatch, tmp_path):
    empty_path = _build_empty_db(tmp_path)
    monkeypatch.setenv("CUS_DB", str(empty_path))
    monkeypatch.setenv("CUS_CONFIG", str(tmp_path / "missing-config.toml"))

    client = TestClient(app)

    response = client.get("/")

    assert response.status_code == 200
    assert "No plan snapshots yet. Wire" in response.text
