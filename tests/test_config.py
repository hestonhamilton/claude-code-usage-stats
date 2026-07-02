from datetime import date
from pathlib import Path

import pytest

from cus.config import load_config


def test_load_config_parses_ssh_and_local_machines(tmp_path):
    config_path = tmp_path / "machines.toml"
    config_path.write_text(
        """
[central]
db_path = "/data/cus.db"
staging_dir = "/staging"
pull_interval_minutes = 10
price_refresh_hours = 12
litellm_url = "https://example.test/prices.json"

[[machines]]
id = "example-host"
transport = "ssh"
host = "192.168.10.20"
user = "user"
ssh_key = "/keys/id_ed25519"
remote_path = "/home/user/.claude/projects"
rate_limit_log = "/home/user/.claude/rate-limits.jsonl"

[[machines]]
id = "central-local"
transport = "local"
path = "/tmp/projects"
rate_limit_log = "/tmp/rate-limits.jsonl"
""",
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.central.db_path == Path("/data/cus.db")
    assert config.central.staging_dir == Path("/staging")
    assert config.central.pull_interval_minutes == 10
    assert config.central.price_refresh_hours == 12
    assert config.central.litellm_url == "https://example.test/prices.json"
    assert [machine.id for machine in config.machines] == ["example-host", "central-local"]
    assert config.machines[0].transport == "ssh"
    assert config.machines[0].host == "192.168.10.20"
    assert config.machines[0].ssh_key == Path("/keys/id_ed25519")
    assert config.machines[0].remote_path == Path("/home/user/.claude/projects")
    assert config.machines[0].rate_limit_log == Path("/home/user/.claude/rate-limits.jsonl")
    assert config.machines[1].transport == "local"
    assert config.machines[1].path == Path("/tmp/projects")
    assert config.machines[1].rate_limit_log == Path("/tmp/rate-limits.jsonl")
    assert config.subscription is None


def _base_config(extra: str = "") -> str:
    return (
        """
[central]
db_path = "/data/cus.db"
staging_dir = "/staging"

[[machines]]
id = "example-host"
transport = "local"
path = "/tmp/projects"
"""
        + extra
    )


def test_load_config_parses_multi_period_subscription(tmp_path):
    config_path = tmp_path / "machines.toml"
    config_path.write_text(
        _base_config(
            """
[[subscription.periods]]
plan = "pro"
monthly_usd = 20.0
started_on = 2026-03-24
ended_on = 2026-05-29

[[subscription.periods]]
plan = "max5"
monthly_usd = 100.00
started_on = "2026-05-29"
"""
        ),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.subscription is not None
    assert len(config.subscription.periods) == 2
    pro, max5 = config.subscription.periods
    assert pro.plan == "pro"
    assert pro.monthly_usd == 20.0
    assert pro.started_on == date(2026, 3, 24)
    assert pro.ended_on == date(2026, 5, 29)
    assert max5.monthly_usd == 100.00
    assert max5.started_on == date(2026, 5, 29)
    assert max5.ended_on is None  # ongoing


def test_load_config_without_subscription_block_leaves_it_none(tmp_path):
    config_path = tmp_path / "machines.toml"
    config_path.write_text(_base_config(), encoding="utf-8")

    config = load_config(config_path)

    assert config.subscription is None


def test_load_config_rejects_empty_periods_list(tmp_path):
    config_path = tmp_path / "machines.toml"
    config_path.write_text(
        _base_config(
            """
[subscription]
"""
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="periods"):
        load_config(config_path)


def test_load_config_rejects_non_positive_monthly_usd(tmp_path):
    config_path = tmp_path / "machines.toml"
    config_path.write_text(
        _base_config(
            """
[[subscription.periods]]
monthly_usd = 0
started_on = 2026-01-15
"""
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="monthly_usd"):
        load_config(config_path)


def test_load_config_rejects_missing_started_on(tmp_path):
    config_path = tmp_path / "machines.toml"
    config_path.write_text(
        _base_config(
            """
[[subscription.periods]]
monthly_usd = 100.0
"""
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="started_on"):
        load_config(config_path)


def test_load_config_rejects_ended_before_started(tmp_path):
    config_path = tmp_path / "machines.toml"
    config_path.write_text(
        _base_config(
            """
[[subscription.periods]]
monthly_usd = 100.0
started_on = 2026-05-01
ended_on = 2026-04-01
"""
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="ended_on"):
        load_config(config_path)


def test_load_config_missing_required_transport_field_raises(tmp_path):
    config_path = tmp_path / "machines.toml"
    config_path.write_text(
        """
[central]
db_path = "/data/cus.db"
staging_dir = "/staging"

[[machines]]
id = "example-host"
transport = "ssh"
host = "192.168.10.20"
user = "user"
remote_path = "/home/user/.claude/projects"
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="ssh_key"):
        load_config(config_path)


def test_load_config_unknown_transport_raises(tmp_path):
    config_path = tmp_path / "machines.toml"
    config_path.write_text(
        """
[central]
db_path = "/data/cus.db"
staging_dir = "/staging"

[[machines]]
id = "example-host"
transport = "sftp"
path = "/tmp/projects"
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unknown transport"):
        load_config(config_path)
