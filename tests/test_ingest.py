import shutil
import sqlite3
import json
import math
from pathlib import Path

from cus.db import connect, init_db
from cus.ingest import ingest_dir, ingest_file, reprice_events
from cus.pricing import load_prices


FIXTURE_DIR = Path(__file__).parent / "fixtures"
FIXTURE = FIXTURE_DIR / "project-one" / "session-1.jsonl"

# Separate tree (not under FIXTURE_DIR) covering the multi-line-per-response
# dedup semantics, kept isolated so it doesn't perturb the counts/costs
# asserted against FIXTURE_DIR elsewhere in this file and in
# test_highlights.py / test_pull.py / test_web.py.
DEDUP_FIXTURE_DIR = Path(__file__).parent / "fixtures_dedup"


def _conn(tmp_path: Path) -> sqlite3.Connection:
    conn = connect(tmp_path / "usage.db")
    init_db(conn)
    return conn


def test_ingest_is_idempotent_for_events_and_tool_uses(tmp_path):
    conn = _conn(tmp_path)
    try:
        first = ingest_dir(conn, FIXTURE_DIR, "testbox")
        second = ingest_dir(conn, FIXTURE_DIR, "testbox")

        assert first["events"] == 3
        assert first["tool_uses"] == 3
        assert first["skipped"] == 1
        assert first["unpriced"] == 1
        assert math.isclose(first["cost_usd"], 0.00172835)
        assert second["events"] == 0
        assert second["tool_uses"] == 0
        assert second["skipped"] == 0
        assert second["unpriced"] == 0
        assert second["cost_usd"] == 0.0
        assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 3
        assert conn.execute("SELECT COUNT(*) FROM tool_uses").fetchone()[0] == 3
    finally:
        conn.close()


def test_offset_resume_only_reads_appended_lines(tmp_path):
    session_copy = tmp_path / "projects" / "slug" / "session-copy.jsonl"
    session_copy.parent.mkdir(parents=True)
    shutil.copyfile(FIXTURE, session_copy)

    conn = _conn(tmp_path)
    try:
        first = ingest_file(conn, session_copy, "testbox")
        assert first["events"] == 2

        with session_copy.open("a", encoding="utf-8") as handle:
            handle.write(
                '\n{"type":"assistant","uuid":"event-3","timestamp":"2026-06-16T02:55:00.000Z",'
                '"sessionId":"session-1","cwd":"/work/project-one","gitBranch":"main",'
                '"isSidechain":false,"message":{"role":"assistant","model":"claude-opus-4-8",'
                '"usage":{"input_tokens":9,"output_tokens":4,"cache_creation_input_tokens":3,'
                '"cache_read_input_tokens":2,"service_tier":"standard",'
                '"cache_creation":{"ephemeral_1h_input_tokens":1,"ephemeral_5m_input_tokens":2},'
                '"server_tool_use":{"web_search_requests":1,"web_fetch_requests":0}},'
                '"content":[{"type":"tool_use","name":"Glob","input":{}}]}}'
            )

        second = ingest_file(conn, session_copy, "testbox")

        assert second["events"] == 1
        assert second["tool_uses"] == 1
        assert second["skipped"] == 0
        assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 3
        assert conn.execute("SELECT COUNT(*) FROM tool_uses").fetchone()[0] == 4
    finally:
        conn.close()


def test_session_rollup_sums_events_and_latest_title(tmp_path):
    conn = _conn(tmp_path)
    try:
        ingest_dir(conn, FIXTURE_DIR, "testbox")
        row = conn.execute(
            "SELECT * FROM sessions WHERE session_id = ?",
            ("session-1",),
        ).fetchone()

        assert row["machine_id"] == "testbox"
        assert row["cwd"] == "/work/project-one"
        assert row["title"] == "Final title"
        assert row["first_ts"] == "2026-06-16T02:53:44.170Z"
        assert row["last_ts"] == "2026-06-16T02:54:10.000Z"
        assert row["input_tokens"] == 150
        assert row["output_tokens"] == 35
        assert row["cache_creation_tokens"] == 35
        assert row["cache_read_tokens"] == 47
        assert row["message_count"] == 2
        event_sum = conn.execute(
            "SELECT SUM(cost_usd) FROM events WHERE session_id = ?",
            ("session-1",),
        ).fetchone()[0]
        assert math.isclose(row["cost_usd"], event_sum)
        assert math.isclose(row["cost_usd"], 0.00172835)
    finally:
        conn.close()


def test_ingest_prices_known_models_and_leaves_unknown_null(tmp_path):
    conn = _conn(tmp_path)
    try:
        ingest_dir(conn, FIXTURE_DIR, "testbox")

        assert (
            conn.execute(
                "SELECT COUNT(*) FROM events WHERE model != ? AND cost_usd IS NOT NULL",
                ("<synthetic>",),
            ).fetchone()[0]
            == 2
        )
        assert (
            conn.execute(
                "SELECT cost_usd FROM events WHERE model = ?",
                ("<synthetic>",),
            ).fetchone()[0]
            is None
        )
        assert (
            conn.execute(
                "SELECT cost_usd FROM sessions WHERE session_id = ?",
                ("session-synthetic",),
            ).fetchone()[0]
            is None
        )
    finally:
        conn.close()


def test_multiline_response_dedupes_to_one_event_with_combined_tool_uses(tmp_path):
    # Claude Code writes one JSONL line per content block, but all lines for a
    # single API response share the same message.id and message.usage. The
    # fixture has 3 lines (text, tool_use Read, tool_use Bash) for
    # message.id="msg_dedup_1" plus 2 lines with no message.id.
    conn = _conn(tmp_path)
    try:
        first = ingest_dir(conn, DEDUP_FIXTURE_DIR, "testbox")

        assert first["events"] == 3  # 1 for the grouped response + 2 fallback rows
        assert first["skipped"] == 0

        row = conn.execute(
            "SELECT uuid, message_id, cost_usd FROM events WHERE message_id = ?",
            ("msg_dedup_1",),
        ).fetchone()
        assert row is not None
        assert row["uuid"] == "resp-1a"
        # Usage must be counted ONCE, not summed across the 3 lines that share it.
        assert math.isclose(row["cost_usd"], 0.002)

        assert (
            conn.execute(
                "SELECT COUNT(*) FROM events WHERE message_id = ?",
                ("msg_dedup_1",),
            ).fetchone()[0]
            == 1
        )

        tool_names = {
            r["tool_name"]
            for r in conn.execute(
                "SELECT tool_name FROM tool_uses WHERE event_uuid = ?",
                (row["uuid"],),
            )
        }
        assert tool_names == {"Read", "Bash"}

        second = ingest_dir(conn, DEDUP_FIXTURE_DIR, "testbox")
        assert second["events"] == 0
        assert second["tool_uses"] == 0
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM events WHERE message_id = ?",
                ("msg_dedup_1",),
            ).fetchone()[0]
            == 1
        )
    finally:
        conn.close()


def test_null_message_id_falls_back_to_uuid_dedup(tmp_path):
    conn = _conn(tmp_path)
    try:
        ingest_dir(conn, DEDUP_FIXTURE_DIR, "testbox")

        rows = conn.execute(
            "SELECT uuid, message_id, cost_usd FROM events "
            "WHERE message_id IS NULL ORDER BY uuid"
        ).fetchall()

        # Two distinct records with no message.id must NOT collapse into a
        # single group keyed on None -- each falls back to its own uuid.
        assert [r["uuid"] for r in rows] == ["dedup-null-1", "dedup-null-2"]
        assert math.isclose(rows[0]["cost_usd"], 0.00001)
        assert math.isclose(rows[1]["cost_usd"], 0.000017)
    finally:
        conn.close()


def test_reprice_is_idempotent_and_litellm_override_changes_totals(tmp_path):
    conn = _conn(tmp_path)
    litellm = tmp_path / "model_prices_and_context_window.json"
    litellm.write_text(
        json.dumps(
            {
                "anthropic/claude-opus-4-8": {
                    "input_cost_per_token": 0.000010,
                    "output_cost_per_token": 0.000050,
                }
            }
        ),
        encoding="utf-8",
    )
    try:
        ingest_dir(conn, FIXTURE_DIR, "testbox")

        first = reprice_events(conn)
        second = reprice_events(conn)
        assert first == second
        assert first["priced"] == 2
        assert first["unpriced"] == 1
        assert math.isclose(first["cost_usd"], 0.00172835)

        overridden = reprice_events(conn, prices=load_prices(litellm))
        assert overridden["priced"] == 2
        assert overridden["unpriced"] == 1
        assert math.isclose(overridden["cost_usd"], 0.00313585)
        session_cost = conn.execute(
            "SELECT cost_usd FROM sessions WHERE session_id = ?",
            ("session-1",),
        ).fetchone()[0]
        assert math.isclose(session_cost, overridden["cost_usd"])
    finally:
        conn.close()
