from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from cus import rollups
from cus.config import SubscriptionConfig, load_config
from cus.web import metrics as metrics_mod


WEB_DIR = Path(__file__).parent
DEFAULT_DB = "./data/cus.db"
# Mirrors worker.py's CUS_CONFIG env var; relative default matches DEFAULT_DB
# for host-side `cus serve` usage. The [subscription] block is optional (see
# machines.example.toml) — any missing/invalid config just hides Metric B.
DEFAULT_CONFIG = "./config/machines.toml"

app = FastAPI(title="Claude Usage Stats")
app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")

templates = Jinja2Templates(directory=WEB_DIR / "templates")


def _format_int(value: Any) -> str:
    return f"{int(value or 0):,}"


def _format_cost(value: Any) -> str:
    return f"${float(value or 0):,.2f}"


def _format_tokens(value: Any) -> str:
    number = int(value or 0)
    if abs(number) >= 1_000_000:
        return f"{number / 1_000_000:.1f}M"
    if abs(number) >= 1_000:
        return f"{number / 1_000:.1f}K"
    return f"{number:,}"


def _pct(value: Any, maximum: Any) -> str:
    max_value = float(maximum or 0)
    if max_value <= 0:
        return "0%"
    return f"{max(0.0, min(100.0, (float(value or 0) / max_value) * 100.0)):.1f}%"


def _percent(value: Any) -> str:
    return f"{float(value or 0):.1f}%"


def _ratio(value: Any) -> str:
    if value is None:
        return "—"
    return f"{float(value):.1f}x"


templates.env.filters["intfmt"] = _format_int
templates.env.filters["cost"] = _format_cost
templates.env.filters["tokens"] = _format_tokens
templates.env.filters["pct"] = _pct
templates.env.filters["percent"] = _percent
templates.env.filters["ratio"] = _ratio


def _load_subscription_config() -> SubscriptionConfig | None:
    """Best-effort, optional `[subscription]` config for Metric B.

    Any missing file, missing table, or invalid value degrades to None (hide
    the ROI view) rather than raising — this must never break the dashboard.
    """
    path = Path(os.environ.get("CUS_CONFIG", DEFAULT_CONFIG))
    if not path.exists():
        return None
    try:
        return load_config(path).subscription
    except Exception:
        return None


@contextmanager
def _open_readonly() -> Iterator[sqlite3.Connection | None]:
    path = Path(os.environ.get("CUS_DB", DEFAULT_DB))
    if not path.exists():
        yield None
        return
    # A WAL database must create/attach the -shm wal-index to be read. A mode=ro
    # connection (or a read-only volume mount) cannot do that and SQLite then
    # fails with "unable to open database file". Open read-write so the reader
    # can attach the wal-index, and enforce read-only semantics with
    # PRAGMA query_only (any write raises). The compose `web` service mounts the
    # db volume read-write for the same reason.
    conn = sqlite3.connect(f"file:{path}?mode=rw", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    try:
        yield conn
    finally:
        conn.close()


def get_conn() -> Iterator[sqlite3.Connection | None]:
    with _open_readonly() as conn:
        yield conn


def _filters(machine: str | None, start: str | None, end: str | None) -> dict[str, str | None]:
    return {"machine": machine or None, "start_day": start or None, "end_day": end or None}


def _dashboard_context(
    conn: sqlite3.Connection | None,
    *,
    machine: str | None,
    start: str | None,
    end: str | None,
) -> dict[str, Any]:
    empty_value_realized = {
        "5h": {"peak_pct": None, "avg_pct": None, "windows_realized": 0, "windows_total": 0},
        "7d": {"peak_pct": None, "avg_pct": None, "windows_realized": 0, "windows_total": 0},
    }
    if conn is None:
        return {
            "has_db": False,
            "summary": {},
            "days": [],
            "models": [],
            "machines": [],
            "projects": [],
            "branches": [],
            "top_sessions": [],
            "machine_options": [],
            "max_day_tokens": 0,
            "freshness": {"last_ingest_at": None, "machines": []},
            "plan_status": {"5h": None, "7d": None},
            "value_realized": empty_value_realized,
            "subscription_roi": None,
            "filters": {"machine": machine, "start": start, "end": end},
        }
    filters = _filters(machine, start, end)
    days = rollups.by_day(conn, days=30, **filters)
    subscription = _load_subscription_config()
    roi = None
    if subscription is not None:
        roi = rollups.subscription_roi(
            conn,
            subscription.periods,
            start_day=filters["start_day"],
            end_day=filters["end_day"],
        )
    return {
        "has_db": True,
        "summary": rollups.overview(conn, **filters),
        "freshness": rollups.freshness(conn),
        "days": days,
        "models": rollups.by_model(conn, limit=15, **filters),
        "machines": rollups.by_machine(conn, **filters),
        "projects": rollups.by_project(conn, limit=15, **filters),
        "branches": rollups.by_branch(conn, limit=15, **filters),
        "top_sessions": rollups.top_sessions(conn, limit=10, order_by="cost", **filters),
        "machine_options": rollups.machines(conn),
        "max_day_tokens": max((row["tokens"] for row in days), default=0),
        "plan_status": rollups.plan_status(conn),
        "value_realized": rollups.value_realized(conn, **filters),
        "subscription_roi": roi,
        "filters": {"machine": machine, "start": start, "end": end},
    }


def _highlights_context(
    conn: sqlite3.Connection | None,
    *,
    machine: str | None,
    start: str | None,
    end: str | None,
) -> dict[str, Any]:
    empty_cache = {
        "cache_read_tokens": 0,
        "cost_usd": 0.0,
        "saved_usd": 0.0,
        "effective_discount_pct": 0.0,
    }
    empty_sidechain = {
        "events": 0,
        "sidechain_events": 0,
        "cost_usd": 0.0,
        "sidechain_cost_usd": 0.0,
        "pct_cost": 0.0,
    }
    empty_server_tools = {"web_search_requests": 0, "web_fetch_requests": 0}
    if conn is None:
        return {
            "has_db": False,
            "cache_savings": empty_cache,
            "sidechain_share": empty_sidechain,
            "server_tool_usage": empty_server_tools,
            "hours": [],
            "top_sessions": [],
            "projects": [],
            "branches": [],
            "tool_use_mix": [],
            "most_expensive_prompts": [],
            "machine_options": [],
            "max_hour_tokens": 0,
            "max_project_cost": 0,
            "max_branch_cost": 0,
            "max_tool_count": 0,
            "filters": {"machine": machine, "start": start, "end": end},
        }
    filters = _filters(machine, start, end)
    hours = rollups.by_hour(conn, **filters)
    projects = rollups.by_project(conn, limit=10, **filters)
    branches = rollups.by_branch(conn, limit=10, **filters)
    tool_mix = rollups.tool_use_mix(conn, **filters)
    return {
        "has_db": True,
        "cache_savings": rollups.cache_savings(conn, **filters),
        "sidechain_share": rollups.sidechain_share(conn, **filters),
        "server_tool_usage": rollups.server_tool_usage(conn, **filters),
        "hours": hours,
        "top_sessions": rollups.top_sessions(conn, limit=10, order_by="cost", **filters),
        "projects": projects,
        "branches": branches,
        "tool_use_mix": tool_mix,
        "most_expensive_prompts": rollups.most_expensive_prompts(conn, limit=10, **filters),
        "machine_options": rollups.machines(conn),
        "max_hour_tokens": max((row["tokens"] for row in hours), default=0),
        "max_project_cost": max((row["cost_usd"] for row in projects), default=0),
        "max_branch_cost": max((row["cost_usd"] for row in branches), default=0),
        "max_tool_count": max((row["count"] for row in tool_mix), default=0),
        "filters": {"machine": machine, "start": start, "end": end},
    }


def _trends_context(
    conn: sqlite3.Connection | None,
    *,
    machine: str | None,
    start: str | None,
    end: str | None,
) -> dict[str, Any]:
    if conn is None:
        return {
            "has_db": False,
            "weeks": [],
            "trend": [],
            "cache_timeline": [],
            "model_mix": {"top_models": [], "periods": []},
            "machine_options": [],
            "max_trend_value": 0,
            "filters": {"machine": machine, "start": start, "end": end},
        }
    filters = _filters(machine, start, end)
    trend = rollups.cost_trend(conn, window=7, **filters)
    cache_timeline = rollups.cache_efficiency_timeline(conn, by="week", **filters)
    max_trend_value = max(
        (max(row["cost_usd"], row["cost_ma"]) for row in trend),
        default=0,
    )
    return {
        "has_db": True,
        "weeks": rollups.by_week(conn, **filters),
        "trend": trend,
        "cache_timeline": cache_timeline,
        "model_mix": rollups.model_mix_timeline(conn, by="week", top=6, **filters),
        "machine_options": rollups.machines(conn),
        "max_trend_value": max_trend_value,
        "filters": {"machine": machine, "start": start, "end": end},
    }


@app.get("/healthz")
def healthz() -> dict[str, bool]:
    return {"ok": True}


@app.get("/metrics")
def metrics(
    conn: sqlite3.Connection | None = Depends(get_conn),
) -> PlainTextResponse:
    """Prometheus exposition of headline usage/value gauges.

    Always returns 200 with a valid body (even without a DB) so a scrape never
    looks like a failure; `cus_db_available` reports the DB's presence.
    """
    body = metrics_mod.render_metrics(conn, _load_subscription_config())
    return PlainTextResponse(body, media_type=metrics_mod.CONTENT_TYPE)


@app.get("/", response_class=HTMLResponse)
def dashboard(
    request: Request,
    machine: str | None = None,
    start: str | None = Query(default=None, pattern=r"^(\d{4}-\d{2}-\d{2})?$"),
    end: str | None = Query(default=None, pattern=r"^(\d{4}-\d{2}-\d{2})?$"),
    conn: sqlite3.Connection | None = Depends(get_conn),
) -> HTMLResponse:
    context = _dashboard_context(conn, machine=machine, start=start, end=end)
    context["request"] = request
    return templates.TemplateResponse(request, "dashboard.html", context)


@app.get("/partials/breakdowns", response_class=HTMLResponse)
def breakdowns(
    request: Request,
    machine: str | None = None,
    start: str | None = Query(default=None, pattern=r"^(\d{4}-\d{2}-\d{2})?$"),
    end: str | None = Query(default=None, pattern=r"^(\d{4}-\d{2}-\d{2})?$"),
    conn: sqlite3.Connection | None = Depends(get_conn),
) -> HTMLResponse:
    context = _dashboard_context(conn, machine=machine, start=start, end=end)
    context["request"] = request
    return templates.TemplateResponse(request, "partials/breakdowns.html", context)


@app.get("/highlights", response_class=HTMLResponse)
def highlights(
    request: Request,
    machine: str | None = None,
    start: str | None = Query(default=None, pattern=r"^(\d{4}-\d{2}-\d{2})?$"),
    end: str | None = Query(default=None, pattern=r"^(\d{4}-\d{2}-\d{2})?$"),
    conn: sqlite3.Connection | None = Depends(get_conn),
) -> HTMLResponse:
    context = _highlights_context(conn, machine=machine, start=start, end=end)
    context["request"] = request
    return templates.TemplateResponse(request, "highlights.html", context)


@app.get("/trends", response_class=HTMLResponse)
def trends(
    request: Request,
    machine: str | None = None,
    start: str | None = Query(default=None, pattern=r"^(\d{4}-\d{2}-\d{2})?$"),
    end: str | None = Query(default=None, pattern=r"^(\d{4}-\d{2}-\d{2})?$"),
    conn: sqlite3.Connection | None = Depends(get_conn),
) -> HTMLResponse:
    context = _trends_context(conn, machine=machine, start=start, end=end)
    context["request"] = request
    return templates.TemplateResponse(request, "trends.html", context)


@app.get("/plan", response_class=HTMLResponse)
def plan(
    request: Request,
    conn: sqlite3.Connection | None = Depends(get_conn),
) -> HTMLResponse:
    status = {"5h": None, "7d": None}
    timelines = {"5h": [], "7d": []}
    if conn is not None:
        status = rollups.plan_status(conn)
        timelines = {
            "5h": rollups.plan_timeline(conn, "5h"),
            "7d": rollups.plan_timeline(conn, "7d"),
        }
    return templates.TemplateResponse(
        request,
        "plan.html",
        {
            "request": request,
            "has_db": conn is not None,
            "status": status,
            "timelines": timelines,
        },
    )


@app.get("/sessions", response_class=HTMLResponse)
def sessions(
    request: Request,
    order: str = Query(default="recent", pattern="^(cost|recent)$"),
    conn: sqlite3.Connection | None = Depends(get_conn),
) -> HTMLResponse:
    rows = [] if conn is None else rollups.top_sessions(conn, limit=50, order_by=order)
    return templates.TemplateResponse(
        request,
        "sessions.html",
        {"request": request, "sessions": rows, "order": order, "has_db": conn is not None},
    )


@app.get("/session/{session_id}", response_class=HTMLResponse)
def session(
    request: Request,
    session_id: str,
    conn: sqlite3.Connection | None = Depends(get_conn),
) -> HTMLResponse:
    if conn is None:
        raise HTTPException(status_code=404, detail="Session not found")
    detail = rollups.session_detail(conn, session_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return templates.TemplateResponse(
        request,
        "session.html",
        {"request": request, "session": detail, "has_db": True},
    )
