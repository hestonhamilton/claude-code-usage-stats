from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .config import Config, MachineConfig, load_config
from .pull import RSYNC_FLAGS, SSH_OPTIONS


@dataclass(frozen=True)
class CheckResult:
    machine_id: str
    status: str
    reason: str


@dataclass(frozen=True)
class DoctorResult:
    checks: tuple[CheckResult, ...]

    @property
    def failed(self) -> bool:
        return any(check.status == "FAIL" for check in self.checks)


def load_config_for_doctor(path: str | Path) -> tuple[Config | None, str | None]:
    try:
        return load_config(path), None
    except Exception as exc:
        return None, f"config validation failed: {exc}"


def run_doctor(config: Config) -> DoctorResult:
    checks = [_check_central(config)]
    checks.extend(_check_machine(machine) for machine in config.machines)
    return DoctorResult(tuple(checks))


def _check_central(config: Config) -> CheckResult:
    try:
        _assert_writable_dir(config.central.db_path.parent)
        _assert_writable_dir(config.central.staging_dir)
    except Exception as exc:
        return CheckResult("central", "FAIL", str(exc))
    return CheckResult(
        "central",
        "OK",
        f"writable db parent {config.central.db_path.parent}; staging {config.central.staging_dir}",
    )


def _assert_writable_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    probe = path / ".cus-doctor-write-test"
    probe.write_text("ok\n", encoding="utf-8")
    probe.unlink()


def _check_machine(machine: MachineConfig) -> CheckResult:
    try:
        if machine.transport == "local":
            return _check_local(machine)
        if machine.transport == "ssh":
            return _check_ssh(machine)
        return CheckResult(machine.id, "FAIL", f"unknown transport {machine.transport!r}")
    except Exception as exc:
        return CheckResult(machine.id, "FAIL", str(exc))


def _check_local(machine: MachineConfig) -> CheckResult:
    if machine.path is None:
        return CheckResult(machine.id, "FAIL", "local transport missing path")
    if not machine.path.exists():
        return CheckResult(machine.id, "FAIL", f"path does not exist: {machine.path}")
    if not machine.path.is_dir():
        return CheckResult(machine.id, "FAIL", f"path is not a directory: {machine.path}")
    try:
        count = sum(1 for _ in machine.path.rglob("*.jsonl"))
    except OSError as exc:
        return CheckResult(machine.id, "FAIL", f"path is not readable: {exc}")
    reason = f"readable local path; found {count} jsonl file(s)"
    if machine.rate_limit_log is not None and not machine.rate_limit_log.exists():
        return CheckResult(machine.id, "WARN", f"{reason}; rate_limit_log missing: {machine.rate_limit_log}")
    return CheckResult(machine.id, "OK", reason)


def _check_ssh(machine: MachineConfig) -> CheckResult:
    if (
        machine.host is None
        or machine.user is None
        or machine.ssh_key is None
        or machine.remote_path is None
    ):
        return CheckResult(machine.id, "FAIL", "ssh transport missing host/user/ssh_key/remote_path")

    ssh = _ssh_command(machine)
    target = f"{machine.user}@{machine.host}"
    reachability = _run([*ssh, target, "true"], timeout=10)
    if reachability.returncode != 0:
        return CheckResult(machine.id, "FAIL", f"ssh failed: {_output(reachability)}")

    with tempfile.TemporaryDirectory(prefix="cus-doctor-") as tmp:
        source = f"{target}:{_source_with_trailing_slash(machine.remote_path)}"
        rsync = _run(
            ["rsync", "-n", *RSYNC_FLAGS, "-e", " ".join(ssh), source, f"{tmp}/"],
            timeout=30,
        )
        if rsync.returncode != 0:
            return CheckResult(machine.id, "FAIL", f"rsync dry-run failed: {_output(rsync)}")

        if machine.rate_limit_log is not None:
            rate_source = f"{target}:{machine.rate_limit_log}"
            rate_check = _run(
                ["rsync", "-n", *RSYNC_FLAGS, "-e", " ".join(ssh), rate_source, f"{tmp}/rate-limits.jsonl"],
                timeout=15,
            )
            if rate_check.returncode != 0:
                return CheckResult(
                    machine.id,
                    "WARN",
                    f"ssh and transcript rsync OK; rate_limit_log not readable: {_output(rate_check)}",
                )

    return CheckResult(machine.id, "OK", "ssh reachable; transcript rsync dry-run OK")


def _ssh_command(machine: MachineConfig) -> list[str]:
    return [
        "ssh",
        "-i",
        str(machine.ssh_key),
        *SSH_OPTIONS,
        "-o",
        "ConnectTimeout=5",
    ]


def _source_with_trailing_slash(path: Path) -> str:
    return f"{path}/"


def _run(command: list[str], *, timeout: int) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(command, capture_output=True, text=True, check=False, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        output = (exc.stderr or exc.stdout or "command timed out").strip()
        return subprocess.CompletedProcess(command, 124, stdout="", stderr=output)


def _output(result: subprocess.CompletedProcess[str]) -> str:
    output = (result.stderr.strip() or result.stdout.strip() or "no output")
    return " ".join(output.split())
