from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from .config import Config, MachineConfig
from .ingest import ingest_dir
from .ratelimits import ingest_ratelimits_file


RSYNC_FLAGS = ("-az", "--delete")
SSH_OPTIONS = ("-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new")


def _source_with_trailing_slash(path: Path) -> str:
    return f"{path}/"


def _run_rsync(command: list[str]) -> None:
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        stderr = result.stderr.strip() or result.stdout.strip() or "rsync failed with no output"
        raise RuntimeError(f"rsync exited with {result.returncode}: {stderr}")


def _is_missing_file_result(result: subprocess.CompletedProcess[str]) -> bool:
    output = f"{result.stderr}\n{result.stdout}".lower()
    return (
        result.returncode in {23, 24}
        and (
            "no such file" in output
            or "cannot stat" in output
            or "not found" in output
            or "link_stat" in output
        )
    )


def pull_machine(machine: MachineConfig, staging_dir: str | Path) -> Path:
    dest = Path(staging_dir) / machine.id
    dest.mkdir(parents=True, exist_ok=True)
    dest_arg = _source_with_trailing_slash(dest)

    if machine.transport == "ssh":
        if (
            machine.host is None
            or machine.user is None
            or machine.ssh_key is None
            or machine.remote_path is None
        ):
            raise ValueError(f"machine {machine.id!r}: ssh transport is missing required fields")
        ssh_command = " ".join(("ssh", "-i", str(machine.ssh_key), *SSH_OPTIONS))
        source = f"{machine.user}@{machine.host}:{_source_with_trailing_slash(machine.remote_path)}"
        command = ["rsync", *RSYNC_FLAGS, "-e", ssh_command, source, dest_arg]
    elif machine.transport == "local":
        if machine.path is None:
            raise ValueError(f"machine {machine.id!r}: local transport is missing required field 'path'")
        command = ["rsync", *RSYNC_FLAGS, _source_with_trailing_slash(machine.path), dest_arg]
    else:
        raise ValueError(f"machine {machine.id!r}: unknown transport {machine.transport!r}")

    _run_rsync(command)
    return dest


def pull_rate_limit_log(machine: MachineConfig, staging_dir: str | Path) -> Path | None:
    if machine.rate_limit_log is None:
        return None

    dest_dir = Path(staging_dir) / machine.id
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / "rate-limits.jsonl"

    if machine.transport == "ssh":
        if machine.host is None or machine.user is None or machine.ssh_key is None:
            raise ValueError(f"machine {machine.id!r}: ssh transport is missing required fields")
        ssh_command = " ".join(("ssh", "-i", str(machine.ssh_key), *SSH_OPTIONS))
        source = f"{machine.user}@{machine.host}:{machine.rate_limit_log}"
        command = ["rsync", *RSYNC_FLAGS, "-e", ssh_command, source, str(dest)]
    elif machine.transport == "local":
        if not machine.rate_limit_log.exists():
            return None
        command = ["rsync", *RSYNC_FLAGS, str(machine.rate_limit_log), str(dest)]
    else:
        raise ValueError(f"machine {machine.id!r}: unknown transport {machine.transport!r}")

    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        if _is_missing_file_result(result):
            return None
        stderr = result.stderr.strip() or result.stdout.strip() or "rsync failed with no output"
        raise RuntimeError(f"rsync exited with {result.returncode}: {stderr}")
    return dest


def _empty_totals() -> dict[str, int | float]:
    return {
        "files": 0,
        "events": 0,
        "tool_uses": 0,
        "skipped": 0,
        "bytes_read": 0,
        "unpriced": 0,
        "cost_usd": 0.0,
        "account_timeline": 0,
    }


def pull_and_ingest(conn, config: Config) -> dict[str, Any]:
    overall = _empty_totals()
    machine_stats: dict[str, dict[str, Any]] = {}

    for machine in config.machines:
        try:
            dest = pull_machine(machine, config.central.staging_dir)
            result = ingest_dir(conn, dest, machine.id)
        except Exception as exc:
            machine_stats[machine.id] = {"error": str(exc)}
            continue

        stats: dict[str, Any] = {"staging_dir": str(dest), **result}
        try:
            rate_limit_log = pull_rate_limit_log(machine, config.central.staging_dir)
            if rate_limit_log is not None:
                rate_limit_result = ingest_ratelimits_file(conn, rate_limit_log)
                stats["account_timeline"] = rate_limit_result["inserted"]
                stats["rate_limit_skipped"] = rate_limit_result["skipped"]
                result = {**result, "account_timeline": rate_limit_result["inserted"]}
            else:
                stats["account_timeline"] = 0
                result = {**result, "account_timeline": 0}
        except Exception as exc:
            stats["account_timeline"] = 0
            stats["rate_limit_error"] = str(exc)
            result = {**result, "account_timeline": 0}
        machine_stats[machine.id] = stats
        for key in overall:
            overall[key] += result[key]

    errors = sum(1 for stats in machine_stats.values() if "error" in stats)
    return {"machines": machine_stats, "overall": overall, "errors": errors}
