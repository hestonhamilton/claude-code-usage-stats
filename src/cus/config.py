from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any
import tomllib


DEFAULT_LITELLM_URL = (
    "https://raw.githubusercontent.com/BerriAI/litellm/main/"
    "model_prices_and_context_window.json"
)


@dataclass(frozen=True)
class CentralConfig:
    db_path: Path
    staging_dir: Path
    pull_interval_minutes: int = 15
    price_refresh_hours: int = 24
    litellm_url: str = DEFAULT_LITELLM_URL


@dataclass(frozen=True)
class MachineConfig:
    id: str
    transport: str
    host: str | None = None
    user: str | None = None
    ssh_key: Path | None = None
    remote_path: Path | None = None
    path: Path | None = None
    rate_limit_log: Path | None = None


@dataclass(frozen=True)
class SubscriptionPeriod:
    """One plan the account has been on (e.g. Pro, then Max5).

    `ended_on` is None for the current/ongoing plan. Billing is charged on
    `started_on` and each monthly anniversary while the plan is active.
    """

    monthly_usd: float
    started_on: date
    ended_on: date | None = None
    plan: str | None = None


@dataclass(frozen=True)
class SubscriptionConfig:
    """Optional `[subscription]` block powering Metric B (subscription ROI).

    Holds one or more `[[subscription.periods]]` (a plan change is two periods).
    Do not hardcode a price/date anywhere else — this is the only source.
    """

    periods: tuple[SubscriptionPeriod, ...]


@dataclass(frozen=True)
class Config:
    central: CentralConfig
    machines: tuple[MachineConfig, ...]
    subscription: SubscriptionConfig | None = None


def _required_str(table: dict[str, Any], key: str, context: str) -> str:
    value = table.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{context}: missing required string field {key!r}")
    return value


def _optional_int(table: dict[str, Any], key: str, default: int, context: str) -> int:
    value = table.get(key, default)
    if not isinstance(value, int) or value <= 0:
        raise ValueError(f"{context}: {key!r} must be a positive integer")
    return value


def _parse_machine(raw: dict[str, Any], index: int) -> MachineConfig:
    context = f"machines[{index}]"
    machine_id = _required_str(raw, "id", context)
    transport = _required_str(raw, "transport", context)
    rate_limit_log = raw.get("rate_limit_log")
    if rate_limit_log is not None and not isinstance(rate_limit_log, str):
        raise ValueError(f"{context}: 'rate_limit_log' must be a string when set")
    rate_limit_log_path = Path(rate_limit_log) if rate_limit_log else None

    if transport == "ssh":
        return MachineConfig(
            id=machine_id,
            transport=transport,
            host=_required_str(raw, "host", context),
            user=_required_str(raw, "user", context),
            ssh_key=Path(_required_str(raw, "ssh_key", context)),
            remote_path=Path(_required_str(raw, "remote_path", context)),
            rate_limit_log=rate_limit_log_path,
        )
    if transport == "local":
        return MachineConfig(
            id=machine_id,
            transport=transport,
            path=Path(_required_str(raw, "path", context)),
            rate_limit_log=rate_limit_log_path,
        )
    raise ValueError(f"{context}: unknown transport {transport!r}; expected 'ssh' or 'local'")


def _parse_date(value: Any, context: str, field: str) -> date:
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"{context}: '{field}' must be an ISO date (YYYY-MM-DD)") from exc
    raise ValueError(f"{context}: missing required field '{field}'")


def _parse_subscription_period(raw: Any, index: int) -> SubscriptionPeriod:
    context = f"subscription.periods[{index}]"
    if not isinstance(raw, dict):
        raise ValueError(f"{context}: expected a table")
    monthly_usd = raw.get("monthly_usd")
    if isinstance(monthly_usd, bool) or not isinstance(monthly_usd, int | float) or monthly_usd <= 0:
        raise ValueError(f"{context}: 'monthly_usd' must be a positive number")
    started_on = _parse_date(raw.get("started_on"), context, "started_on")
    ended_on_raw = raw.get("ended_on")
    ended_on = _parse_date(ended_on_raw, context, "ended_on") if ended_on_raw is not None else None
    if ended_on is not None and ended_on < started_on:
        raise ValueError(f"{context}: 'ended_on' must not precede 'started_on'")
    plan = raw.get("plan")
    if plan is not None and not isinstance(plan, str):
        raise ValueError(f"{context}: 'plan' must be a string")
    return SubscriptionPeriod(
        monthly_usd=float(monthly_usd),
        started_on=started_on,
        ended_on=ended_on,
        plan=plan,
    )


def _parse_subscription(raw: Any) -> SubscriptionConfig | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("[subscription]: expected a table")
    periods_raw = raw.get("periods")
    if not isinstance(periods_raw, list) or not periods_raw:
        raise ValueError("[subscription]: requires a non-empty [[subscription.periods]] list")
    periods = tuple(_parse_subscription_period(p, i) for i, p in enumerate(periods_raw))
    return SubscriptionConfig(periods=periods)


def load_config(path: str | Path) -> Config:
    config_path = Path(path)
    with config_path.open("rb") as handle:
        raw = tomllib.load(handle)

    central_raw = raw.get("central")
    if not isinstance(central_raw, dict):
        raise ValueError("missing required [central] table")

    central = CentralConfig(
        db_path=Path(_required_str(central_raw, "db_path", "central")),
        staging_dir=Path(_required_str(central_raw, "staging_dir", "central")),
        pull_interval_minutes=_optional_int(
            central_raw,
            "pull_interval_minutes",
            15,
            "central",
        ),
        price_refresh_hours=_optional_int(central_raw, "price_refresh_hours", 24, "central"),
        litellm_url=_required_str(
            {**central_raw, "litellm_url": central_raw.get("litellm_url", DEFAULT_LITELLM_URL)},
            "litellm_url",
            "central",
        ),
    )

    machines_raw = raw.get("machines")
    if not isinstance(machines_raw, list) or not machines_raw:
        raise ValueError("missing required [[machines]] entries")
    machines = []
    seen_ids: set[str] = set()
    for index, machine_raw in enumerate(machines_raw):
        if not isinstance(machine_raw, dict):
            raise ValueError(f"machines[{index}]: expected a table")
        machine = _parse_machine(machine_raw, index)
        if machine.id in seen_ids:
            raise ValueError(f"machines[{index}]: duplicate machine id {machine.id!r}")
        seen_ids.add(machine.id)
        machines.append(machine)

    subscription = _parse_subscription(raw.get("subscription"))

    return Config(central=central, machines=tuple(machines), subscription=subscription)
