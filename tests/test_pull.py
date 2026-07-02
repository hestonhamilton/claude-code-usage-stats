import shutil
from pathlib import Path

import pytest

from cus.config import CentralConfig, Config, MachineConfig
from cus.db import connect, init_db
from cus.pull import pull_and_ingest


if shutil.which("rsync") is None:
    pytest.skip("rsync is required for pull tests", allow_module_level=True)


FIXTURE_DIR = Path(__file__).parent / "fixtures"


def test_local_pull_and_ingest_tags_machine_and_is_idempotent(tmp_path):
    remote = tmp_path / "remote" / "projects"
    shutil.copytree(FIXTURE_DIR, remote)
    staging = tmp_path / "staging"
    config = Config(
        central=CentralConfig(db_path=tmp_path / "usage.db", staging_dir=staging),
        machines=(
            MachineConfig(
                id="local-testbox",
                transport="local",
                path=remote,
            ),
        ),
    )

    conn = connect(config.central.db_path)
    try:
        init_db(conn)

        first = pull_and_ingest(conn, config)
        staged_files = sorted((staging / "local-testbox").rglob("*.jsonl"))

        assert len(staged_files) == 2
        assert first["errors"] == 0
        assert first["overall"]["files"] == 2
        assert first["overall"]["events"] == 3
        assert first["machines"]["local-testbox"]["events"] == 3
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM events WHERE machine_id = ?",
                ("local-testbox",),
            ).fetchone()[0]
            == 3
        )

        second = pull_and_ingest(conn, config)

        assert second["errors"] == 0
        assert second["overall"]["events"] == 0
        assert second["machines"]["local-testbox"]["events"] == 0
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM events WHERE machine_id = ?",
                ("local-testbox",),
            ).fetchone()[0]
            == 3
        )
    finally:
        conn.close()
