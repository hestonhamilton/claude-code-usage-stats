from __future__ import annotations

import argparse
import logging
import os

from .config import load_config
from .scheduler import run_price_refresh, run_pull_cycle


LOGGER = logging.getLogger(__name__)


def _run_logged(name: str, func, config) -> None:
    try:
        func(config)
    except Exception:
        LOGGER.exception("%s failed", name)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m cus.worker")
    parser.add_argument("--config", default=os.environ.get("CUS_CONFIG", "/config/machines.toml"))
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=os.environ.get("CUS_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    args = build_parser().parse_args(argv)
    config = load_config(args.config)

    _run_logged("initial pull cycle", run_pull_cycle, config)

    from apscheduler.schedulers.blocking import BlockingScheduler

    scheduler = BlockingScheduler(
        executors={"default": {"type": "threadpool", "max_workers": 1}},
        job_defaults={"coalesce": True, "max_instances": 1},
    )
    scheduler.add_job(
        _run_logged,
        "interval",
        minutes=config.central.pull_interval_minutes,
        args=("pull cycle", run_pull_cycle, config),
        id="pull",
    )
    scheduler.add_job(
        _run_logged,
        "interval",
        hours=config.central.price_refresh_hours,
        args=("price refresh", run_price_refresh, config),
        id="price_refresh",
    )
    LOGGER.info(
        "worker scheduled: pull_interval_minutes=%s price_refresh_hours=%s",
        config.central.pull_interval_minutes,
        config.central.price_refresh_hours,
    )
    scheduler.start()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
