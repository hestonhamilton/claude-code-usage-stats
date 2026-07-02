import math
import sqlite3
from pathlib import Path

from cus import rollups
from cus.db import connect, init_db
from cus.ingest import ingest_dir


FIXTURE_DIR = Path(__file__).parent / "fixtures"


def _build_conn(tmp_path: Path) -> sqlite3.Connection:
    conn = connect(tmp_path / "usage.db")
    init_db(conn)
    ingest_dir(conn, FIXTURE_DIR, "testbox")
    return conn


def test_cache_savings_uses_cache_read_discount_for_priced_models(tmp_path):
    conn = _build_conn(tmp_path)
    try:
        result = rollups.cache_savings(conn)
    finally:
        conn.close()

    expected_saved = (40 * 0.000005 * 0.90) + (7 * 0.000003 * 0.90)
    expected_cost = 0.0014075 + 0.00032085

    assert result["cache_read_tokens"] == 47
    assert math.isclose(result["saved_usd"], expected_saved)
    assert math.isclose(result["cost_usd"], expected_cost)
    assert math.isclose(
        result["effective_discount_pct"],
        expected_saved / (expected_cost + expected_saved),
    )


def test_sidechain_share_and_server_tool_usage(tmp_path):
    conn = _build_conn(tmp_path)
    try:
        sidechain = rollups.sidechain_share(conn)
        server_tools = rollups.server_tool_usage(conn)
    finally:
        conn.close()

    assert sidechain["events"] == 3
    assert sidechain["sidechain_events"] == 1
    assert math.isclose(sidechain["sidechain_cost_usd"], 0.00032085)
    assert math.isclose(sidechain["cost_usd"], 0.0014075 + 0.00032085)
    assert math.isclose(sidechain["pct_cost"], 0.00032085 / (0.0014075 + 0.00032085))
    assert server_tools == {"web_search_requests": 2, "web_fetch_requests": 4}


def test_by_hour_returns_24_rows_summing_to_corpus_totals(tmp_path):
    conn = _build_conn(tmp_path)
    try:
        hours = rollups.by_hour(conn)
        overview = rollups.overview(conn)
    finally:
        conn.close()

    assert [row["hour"] for row in hours] == list(range(24))
    assert sum(row["events"] for row in hours) == overview["events"]
    assert sum(row["tokens"] for row in hours) == overview["total_tokens"]
    assert math.isclose(sum(row["cost_usd"] for row in hours), overview["cost_usd"])


def test_most_expensive_prompts_orders_by_cost(tmp_path):
    conn = _build_conn(tmp_path)
    try:
        rows = rollups.most_expensive_prompts(conn, limit=2)
    finally:
        conn.close()

    assert [row["uuid"] for row in rows] == ["event-1", "event-2"]
    assert rows[0]["cost_usd"] > rows[1]["cost_usd"]
