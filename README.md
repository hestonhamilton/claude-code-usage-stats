# claude-usage-stats

![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)
![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)

A lightweight, self-hosted dashboard that aggregates **Claude Code** transcript
data from an arbitrary number of machines into one SQLite database and shows
usage at several granularities (time, session, project, branch, machine) with
accurate cost, plan-aware rate-limit tracking, and derived "highlights".

Unlike most Claude Code usage tools, this is **multi-machine first** (a central
host pulls from the others) and prices usage from a **LiteLLM-backed** table with
the correct Anthropic prompt-cache multipliers. See [DESIGN.md](DESIGN.md) for the
locked design decisions and sourced cost model.

Stack: FastAPI + Jinja2 + htmx + SQLite. Python 3.12. Core ingest is stdlib-only;
the web and worker are optional extras.

> **Status:** a personal tool built for my own machines, shared as-is in case it's
> useful to others. Maintained on a best-effort basis — issues and PRs are welcome.

## Install

```sh
pip install -e .            # core: ingest + cost + CLI
pip install -e '.[web]'     # + dashboard (fastapi, uvicorn, jinja2)
pip install -e '.[worker]'  # + scheduler (apscheduler) for the pull worker
```

## CLI

```sh
cus ingest --projects-dir ~/.claude/projects --db ./data/cus.db   # ingest transcripts
cus stats  --db ./data/cus.db                                     # totals + cost + unpriced
cus reprice --db ./data/cus.db [--litellm model_prices.json]      # recompute cost after a price refresh
cus pull   --config config/machines.toml                          # one-shot multi-machine pull + ingest
cus serve  --db ./data/cus.db --host 127.0.0.1 --port 8765        # run the dashboard
```

Ingest is idempotent (keyed on each record's `uuid`) and incremental (per-file
byte offset), so re-running is cheap and never double-counts.

## Dashboard routes

`/` overview (KPIs + by-day/model/machine/project) · `/sessions` · `/session/{id}` ·
`/plan` (5h/7d rate-limit windows) · `/highlights` (cache savings, cost by
project/branch, biggest turns, tool-use mix, subagent share, activity by hour) ·
`/metrics` (Prometheus exposition) · `/healthz`.

## Grafana / Prometheus

`/metrics` exposes headline usage & value as Prometheus gauges (API-equivalent
value, subscription ROI, cache savings, plan utilization, data freshness). Point
your existing Prometheus at it and import the ready-made Grafana dashboard, or
spin up a bundled stack with `docker compose --profile grafana up`. Full setup:
[`deploy/grafana/README.md`](deploy/grafana/README.md).

## Docker Compose (central host)

Two services share a `db` volume: `worker` is the **sole writer** (pulls each
machine over ssh/rsync, ingests, refreshes LiteLLM prices on a schedule); `web`
serves the dashboard. The web service opens the DB with `PRAGMA query_only` — it
cannot write — but the volume is mounted read-write because SQLite WAL readers
must attach the `-shm` wal-index (a `:ro` mount fails to open a WAL database).

```sh
cp config/machines.example.toml config/machines.toml   # then edit (see below)
mkdir -p keys && chmod 700 keys
cp /path/to/deploy_key keys/id_ed25519 && chmod 600 keys/id_ed25519
docker compose up --build -d
```

Dashboard: `http://localhost:8765` (host port is 8765 to avoid the common `:8080`
clash; change the left side of the `ports:` mapping freely). `config/machines.toml`
and `keys/` are git-ignored.

### Configure machines

Each `[[machines]]` entry needs a stable `id` (becomes `machine_id`). For SSH:
set `host`, `user`, `ssh_key = "/keys/id_ed25519"`, `remote_path` (the remote
`~/.claude/projects`), and optionally `rate_limit_log` (the remote
`~/.claude/rate-limits.jsonl`). The deploy key only needs **read** access to
those paths. `transport = "local"` (with `path = ...`) ingests a local directory.

## Plan-aware rate limits (optional, per machine)

Claude Code's 5h/7d subscription windows are only exposed to the statusline
command at runtime. To capture them, wire `scripts/statusline-tee.sh` into your
`claude-statusline.sh` on each machine (it appends each snapshot to
`~/.claude/rate-limits.jsonl`), then point that machine's `rate_limit_log` at the
file. The windows are **per-account**: snapshots from all machines are merged
(deduped), never summed. Powers the `/plan` page.

## Development

```sh
pip install -e '.[web,worker]' pytest httpx2
python -m pytest -q
```

## Deferred / possible follow-ups

- A dedicated data-visualization pass (currently accessible CSS bars, no JS charting lib).
- `recompute_sessions` recomputes per file; batch it once per pull if session counts grow large.
- `plan_status` tie-break for snapshots sharing an exact second-resolution timestamp.
- Additional sources (the schema is source-agnostic); OTEL ingestion.

## License

GNU General Public License v3.0 or later — see [LICENSE](LICENSE). Copyright (C)
2026 claude-code-usage-stats contributors. Third-party attributions are listed in
[NOTICE](NOTICE).
