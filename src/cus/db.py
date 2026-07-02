from __future__ import annotations

import sqlite3
from pathlib import Path


def connect(db_path: str | Path) -> sqlite3.Connection:
    path = Path(db_path)
    if path.parent and str(path.parent) != ".":
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS events (
            uuid TEXT PRIMARY KEY,
            message_id TEXT,
            machine_id TEXT,
            session_id TEXT,
            ts TEXT,
            record_type TEXT,
            model TEXT,
            cwd TEXT,
            git_branch TEXT,
            is_sidechain INTEGER,
            input_tokens INTEGER,
            output_tokens INTEGER,
            cache_creation_tokens INTEGER,
            cache_read_tokens INTEGER,
            ephemeral_1h_tokens INTEGER,
            ephemeral_5m_tokens INTEGER,
            service_tier TEXT,
            web_search INTEGER,
            web_fetch INTEGER,
            cost_usd REAL NULL
        );

        CREATE TABLE IF NOT EXISTS tool_uses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_uuid TEXT NOT NULL,
            tool_name TEXT NOT NULL,
            FOREIGN KEY (event_uuid) REFERENCES events(uuid) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_tool_uses_event_uuid
            ON tool_uses(event_uuid);

        CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY,
            machine_id TEXT,
            cwd TEXT,
            title TEXT,
            first_ts TEXT,
            last_ts TEXT,
            input_tokens INTEGER,
            output_tokens INTEGER,
            cache_creation_tokens INTEGER,
            cache_read_tokens INTEGER,
            message_count INTEGER,
            cost_usd REAL NULL
        );

        CREATE TABLE IF NOT EXISTS machines (
            machine_id TEXT PRIMARY KEY,
            hostname TEXT,
            label TEXT,
            last_ingest_at TEXT
        );

        CREATE TABLE IF NOT EXISTS ingest_state (
            path TEXT PRIMARY KEY,
            machine_id TEXT,
            size INTEGER,
            mtime REAL,
            byte_offset INTEGER
        );

        CREATE TABLE IF NOT EXISTS session_titles (
            session_id TEXT NOT NULL,
            machine_id TEXT NOT NULL,
            title TEXT NOT NULL,
            ts TEXT,
            path TEXT NOT NULL,
            byte_offset INTEGER NOT NULL,
            PRIMARY KEY (session_id, machine_id, path, byte_offset)
        );

        CREATE TABLE IF NOT EXISTS account_timeline (
            ts TEXT,
            window TEXT CHECK(window IN ('5h','7d')),
            used_percentage REAL,
            resets_at INTEGER,
            PRIMARY KEY(window, resets_at, used_percentage)
        );
        """
    )
    _ensure_column(conn, "events", "cost_usd", "REAL NULL")
    _ensure_column(conn, "sessions", "cost_usd", "REAL NULL")
    _ensure_column(conn, "events", "message_id", "TEXT")
    # One events row per API response: message_id is the billing unit. NULLs
    # (older/synthetic records without a message.id) are exempt from the
    # uniqueness constraint (SQLite treats each NULL as distinct), and ingest
    # falls back to deduping on uuid for those.
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_events_message_id ON events(message_id)"
    )
    conn.commit()


def _ensure_column(
    conn: sqlite3.Connection,
    table: str,
    column: str,
    column_type: str,
) -> None:
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")
