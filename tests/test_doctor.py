from pathlib import Path

from cus.cli import main
from cus.config import CentralConfig, Config, MachineConfig
from cus.doctor import run_doctor


def test_doctor_local_transport_ok_counts_jsonl(tmp_path):
    projects = tmp_path / "projects"
    projects.mkdir()
    (projects / "session.jsonl").write_text("{}\n", encoding="utf-8")
    config = Config(
        central=CentralConfig(db_path=tmp_path / "db" / "cus.db", staging_dir=tmp_path / "staging"),
        machines=(MachineConfig(id="localbox", transport="local", path=projects),),
    )

    result = run_doctor(config)

    assert not result.failed
    assert result.checks[0].status == "OK"
    assert result.checks[1].machine_id == "localbox"
    assert result.checks[1].status == "OK"
    assert "found 1 jsonl" in result.checks[1].reason


def test_doctor_local_transport_missing_path_fails(tmp_path):
    config = Config(
        central=CentralConfig(db_path=tmp_path / "db" / "cus.db", staging_dir=tmp_path / "staging"),
        machines=(
            MachineConfig(id="missingbox", transport="local", path=tmp_path / "missing-projects"),
        ),
    )

    result = run_doctor(config)

    assert result.failed
    assert result.checks[1].machine_id == "missingbox"
    assert result.checks[1].status == "FAIL"
    assert "does not exist" in result.checks[1].reason


def test_doctor_cli_reports_config_validation_errors(tmp_path, capsys):
    config_path = tmp_path / "machines.toml"
    config_path.write_text(
        """
[central]
db_path = "/data/cus.db"
staging_dir = "/staging"
""",
        encoding="utf-8",
    )

    exit_code = main(["doctor", "--config", str(config_path)])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "config validation failed" in captured.err
    assert "machines" in captured.err
