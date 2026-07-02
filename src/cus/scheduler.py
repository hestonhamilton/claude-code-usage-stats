from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .config import Config
from .db import connect, init_db
from .ingest import reprice_events
from .pricing import fetch_litellm, load_prices
from .pull import pull_and_ingest


LOGGER = logging.getLogger(__name__)


def price_cache_path(config: Config) -> Path:
    return Path(config.central.db_path).with_name("model_prices_and_context_window.json")


def run_pull_cycle(config: Config) -> dict[str, Any]:
    conn = connect(config.central.db_path)
    try:
        init_db(conn)
        result = pull_and_ingest(conn, config)
    finally:
        conn.close()
    overall = result["overall"]
    LOGGER.info(
        "pull cycle complete: files=%s events=%s tool_uses=%s skipped=%s "
        "bytes_read=%s unpriced=%s cost_usd=%.12f errors=%s",
        overall["files"],
        overall["events"],
        overall["tool_uses"],
        overall["skipped"],
        overall["bytes_read"],
        overall["unpriced"],
        overall["cost_usd"],
        result["errors"],
    )
    for machine_id, stats in result["machines"].items():
        if "error" in stats:
            LOGGER.error("pull failed for %s: %s", machine_id, stats["error"])
    return result


def run_price_refresh(config: Config) -> dict[str, Any]:
    cache_path = price_cache_path(config)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    fetch_litellm(config.central.litellm_url, cache_path)
    prices = load_prices(cache_path)

    conn = connect(config.central.db_path)
    try:
        init_db(conn)
        result = reprice_events(conn, prices=prices)
    finally:
        conn.close()
    LOGGER.info(
        "price refresh complete: priced=%s unpriced=%s cost_usd=%.12f",
        result["priced"],
        result["unpriced"],
        result["cost_usd"],
    )
    return result
