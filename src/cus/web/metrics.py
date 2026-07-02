"""Prometheus exposition of Claude usage stats.

Emits a small set of low-cardinality **gauges** derived from `rollups.py`, in
the Prometheus text exposition format (version 0.0.4). Gauges — not counters —
because the underlying data is a point-in-time ingested snapshot: the honest
reading of `cus_api_equivalent_value_usd` is "cumulative value as of the last
ingest", which steps up when new data lands. Scraped repeatedly it stays flat
between ingests; Prometheus accrues the trend on its own going forward. Using
counters here would make `rate()` smear each ingest jump across the scrape
interval, which would misrepresent the data.

The base package has zero third-party dependencies by design, so the exposition
format is hand-rolled rather than pulling in `prometheus_client`. The surface is
small and fully covered by tests.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Any, Mapping

from cus import rollups
from cus.config import SubscriptionConfig

CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"


def _fmt(value: Any) -> str:
    """Format a numeric value for the exposition format."""
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int):
        return str(value)
    number = float(value)
    if number != number:  # NaN
        return "NaN"
    if number in (float("inf"), float("-inf")):
        return "+Inf" if number > 0 else "-Inf"
    # %.10g keeps currency (cent precision) exact and ratios compact, without
    # scientific notation for the magnitudes we deal in.
    return f"{number:.10g}"


def _escape_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _iso_to_epoch(value: str | None) -> float | None:
    """Best-effort ISO-8601 string -> unix seconds; naive stamps assumed UTC."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


class _Exposition:
    """Accumulates metric lines, emitting HELP/TYPE once per metric family."""

    def __init__(self) -> None:
        self._lines: list[str] = []
        self._declared: set[str] = set()

    def gauge(
        self,
        name: str,
        help_text: str,
        value: Any,
        labels: Mapping[str, str] | None = None,
    ) -> None:
        # A missing value (no data for this metric) is simply omitted rather
        # than emitted as 0 — 0 and "unknown" are different, and NaN would
        # pollute aggregations.
        if value is None:
            return
        if name not in self._declared:
            self._lines.append(f"# HELP {name} {help_text}")
            self._lines.append(f"# TYPE {name} gauge")
            self._declared.add(name)
        label_str = ""
        if labels:
            inner = ",".join(
                f'{key}="{_escape_label(val)}"' for key, val in labels.items()
            )
            label_str = "{" + inner + "}"
        self._lines.append(f"{name}{label_str} {_fmt(value)}")

    def render(self) -> str:
        return "\n".join(self._lines) + "\n"


def render_metrics(
    conn: sqlite3.Connection | None,
    subscription: SubscriptionConfig | None = None,
) -> str:
    """Render the full `/metrics` body for the current DB snapshot.

    `conn` may be None (DB not yet present) — the exporter still returns a valid
    body reporting `cus_up 1` and `cus_db_available 0` so the scrape succeeds and
    the absence is observable in Grafana rather than looking like a scrape error.
    """
    exp = _Exposition()
    exp.gauge("cus_up", "Whether the exporter responded (always 1).", 1)
    exp.gauge(
        "cus_db_available",
        "Whether the usage database was present and readable (1) or not (0).",
        1 if conn is not None else 0,
    )
    if conn is None:
        return exp.render()

    overview = rollups.overview(conn)
    exp.gauge(
        "cus_api_equivalent_value_usd",
        "All-time API-equivalent value of usage in USD (sum of per-event "
        "API-priced cost).",
        overview.get("cost_usd"),
    )
    exp.gauge(
        "cus_events",
        "Total billed API responses (events) ingested.",
        overview.get("events"),
    )
    exp.gauge(
        "cus_sessions",
        "Distinct Claude Code sessions ingested.",
        overview.get("sessions"),
    )
    exp.gauge(
        "cus_machines",
        "Distinct machines contributing usage.",
        overview.get("machines"),
    )
    exp.gauge(
        "cus_unpriced_events",
        "Events with no cost attributed (pricing gaps / data-quality signal).",
        overview.get("unpriced_events"),
    )
    for kind in ("input", "output", "cache_creation", "cache_read"):
        exp.gauge(
            "cus_tokens",
            "Cumulative token count by kind.",
            overview.get(f"{kind}_tokens"),
            labels={"kind": kind},
        )

    freshness = rollups.freshness(conn)
    exp.gauge(
        "cus_last_ingest_timestamp_seconds",
        "Unix time of the most recent ingest across all machines "
        "(data-freshness signal).",
        _iso_to_epoch(freshness.get("last_ingest_at")),
    )

    cache = rollups.cache_savings(conn)
    exp.gauge(
        "cus_cache_saved_usd",
        "USD saved by prompt-cache reads vs. uncached input pricing.",
        cache.get("saved_usd"),
    )
    exp.gauge(
        "cus_cache_effective_discount_ratio",
        "Cache savings as a fraction (0-1) of what the uncached cost would have "
        "been.",
        cache.get("effective_discount_pct"),
    )

    plan = rollups.plan_status(conn)
    for window in ("5h", "7d"):
        status = plan.get(window)
        if not status:
            continue
        exp.gauge(
            "cus_plan_used_percentage",
            "Latest plan rate-limit utilization for the window (0-100).",
            status.get("used_percentage"),
            labels={"window": window},
        )
        resets_at = status.get("resets_at")
        exp.gauge(
            "cus_plan_resets_at_seconds",
            "Unix time at which the plan window's utilization resets.",
            resets_at if resets_at is not None else None,
            labels={"window": window},
        )

    if subscription is not None:
        roi = rollups.subscription_roi(conn, subscription.periods)
        if roi is not None:
            exp.gauge(
                "cus_subscription_cost_usd",
                "Subscription cost basis over its active life (USD).",
                roi.get("subscription_usd"),
            )
            exp.gauge(
                "cus_subscription_roi_ratio",
                "API-equivalent value divided by subscription cost "
                "(the ROI multiple).",
                roi.get("ratio"),
            )
            exp.gauge(
                "cus_subscription_billing_cycles",
                "Number of billing cycles counted into the subscription cost.",
                roi.get("cycles"),
            )

    return exp.render()
