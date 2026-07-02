# From 0 to a working Grafana dashboard

A complete runbook for someone new to this project. By the end you'll have the
**Claude Usage & Value** dashboard rendering real numbers (API-equivalent value,
subscription ROI, cache savings, plan utilization, data freshness).

```
Claude Code transcripts ──ingest──> cus.db ──/metrics──> Prometheus ──> Grafana
                                    (SQLite)  (exporter)   (scrape)     (dashboard)
```

Everything on the dashboard is **gauges** derived from the ingested snapshot.
Trend panels accrue over time as Prometheus scrapes — there is **no historical
backfill**, so the "over time" panels start short and fill in as points arrive.

Pick one of two routes:

- **[Route A — Fully containerized](#route-a--fully-containerized)** — you have
  Docker and no existing Prometheus/Grafana. One `docker compose` command brings
  up the app *and* a provisioned Prometheus + Grafana. Fastest 0→dash.
- **[Route B — Bring your own Prometheus + Grafana](#route-b--your-own-prometheus--grafana)**
  — you already run the stack (e.g. at work). Scrape the app and import the
  dashboard JSON.

---

## Prerequisites

- **Route A:** Docker + Docker Compose. That's it.
- **Route B:** Python 3.12 (or Docker) to run the app, plus your existing
  Prometheus and Grafana.
- Some Claude Code usage to look at: `~/.claude/projects` on at least one
  machine. Empty data still renders the dashboard (values just read 0 / *No
  data*), so you can wire it up first and ingest later.

---

## Route A — Fully containerized

Everything runs in Docker: a `worker` ingests transcripts into a SQLite volume,
a `web` service serves the dashboard + `/metrics`, and the `grafana` compose
profile adds a Prometheus that scrapes it and a Grafana with the dashboard
already provisioned.

### 1. Configure where usage comes from

```sh
cp config/machines.example.toml config/machines.toml
```

The `worker` needs at least one source. **To ingest this machine's own Claude
data** (simplest first run), add a `local` source and mount your `~/.claude`
into the worker:

```toml
# config/machines.toml
[[machines]]
id = "laptop"
transport = "local"
path = "/host-claude/projects"
```

```yaml
# docker-compose.yml — under services.worker.volumes, add:
      - ${HOME}/.claude:/host-claude:ro
```

For **remote machines over SSH** instead, see
[`../../RUNBOOK.md`](../../RUNBOOK.md) (deploy key + `transport = "ssh"`).

### 2. Bring the whole stack up

```sh
docker compose --profile grafana up -d --build
```

This starts `worker`, `web`, **plus** Prometheus and Grafana with the datasource
and dashboard auto-provisioned.

### 3. Open it

- **Grafana:** <http://localhost:3000> — login `admin` / `admin` (change it),
  then open **Dashboards → Claude → Claude Usage & Value**.
- Prometheus: <http://localhost:9090> — check **Status → Targets** shows
  `claude-usage-stats` as **UP**.
- The app itself: <http://localhost:8765>.

Give it a scrape interval (60s) for the first points to appear. Stop just the
Grafana extras (leaving the app running) with
`docker compose --profile grafana stop prometheus grafana`.

> The bundled Grafana credentials and Prometheus retention are convenience
> defaults for a local box (see `docker-compose.yml`). Harden them before any
> shared or exposed deployment.

---

## Route B — Your own Prometheus + Grafana

Use this if you already run the stack (recommended when you have one — it needs
no changes to your Grafana provisioning).

### 1. Run the app so `/metrics` is reachable

Local Python:

```sh
pip install -e '.[web]'
cus ingest --projects-dir ~/.claude/projects --db ./data/cus.db   # get data in
cus serve  --db ./data/cus.db --port 8765                          # serve it
```

(Or run just the app in Docker: `docker compose up -d --build`, dashboard on
`:8765`.) Confirm the exporter:

```sh
curl -s localhost:8765/metrics | grep cus_api_equivalent_value_usd
# cus_api_equivalent_value_usd 1234.56
```

### 2. Add a scrape job to your Prometheus

Copy the job from [`../prometheus/prometheus.yml`](../prometheus/prometheus.yml)
into your own `prometheus.yml`, pointing `targets` at wherever the app is
reachable from Prometheus:

```yaml
scrape_configs:
  - job_name: claude-usage-stats
    metrics_path: /metrics
    scrape_interval: 60s
    static_configs:
      - targets: ["your-host:8765"]   # host:port of `cus serve`
        labels: { instance: cus }
```

Reload Prometheus; confirm the target is **UP** under Status → Targets.

### 3. Import the dashboard

In Grafana: **Dashboards → New → Import → Upload JSON file** →
[`dashboards/claude-usage.json`](dashboards/claude-usage.json). On import, pick
your Prometheus in the **Prometheus** datasource dropdown — the dashboard uses a
`datasource` variable, so it binds to whichever you choose. Done.

---

## Verify it worked

- The **API-Equivalent Value** stat shows a non-zero dollar figure.
- **Subscription ROI** shows a multiple (needs a `[subscription]` block — see
  below); otherwise that panel is empty, which is expected.
- **Data Freshness** shows a recent "X ago".
- **Plan Utilization** gauges may show *No data* — expected until plan
  anchor-capture is wired (see below).

If a panel is empty, that's usually honest "no source data", not a wiring bug —
metrics are **omitted, not zeroed**, when their source is absent.

---

## Metrics reference

| Metric | Meaning |
| --- | --- |
| `cus_up` | Exporter responded (always 1). |
| `cus_db_available` | 1 if the usage DB was present/readable, else 0. |
| `cus_api_equivalent_value_usd` | All-time value of usage at API rates (headline). |
| `cus_subscription_roi_ratio` | API-equivalent value ÷ subscription cost. |
| `cus_subscription_cost_usd` | Subscription cost basis over its active life. |
| `cus_subscription_billing_cycles` | Billing cycles counted into the cost. |
| `cus_cache_saved_usd` | USD saved by prompt-cache reads. |
| `cus_cache_effective_discount_ratio` | Cache savings as a fraction (0–1). |
| `cus_tokens{kind}` | Cumulative tokens by kind (input/output/cache_creation/cache_read). |
| `cus_events` / `cus_sessions` / `cus_machines` | Ingested counts. |
| `cus_unpriced_events` | Events with no cost attributed (data-quality signal). |
| `cus_plan_used_percentage{window}` | Latest plan utilization, 5h/7d (0–100). |
| `cus_plan_resets_at_seconds{window}` | Unix time the plan window resets. |
| `cus_last_ingest_timestamp_seconds` | Unix time of the most recent ingest. |

**Subscription metrics** require a `[subscription]` block in
`config/machines.toml` (see `config/machines.example.toml`). Without it, the ROI
panels are simply empty.

**Plan utilization** (`cus_plan_used_percentage` / `cus_plan_resets_at_seconds`)
needs plan anchor-capture populating `account_timeline` — the 5h/7d windows are
only exposed to Claude Code's statusline at runtime. Wire it per
[`../../RUNBOOK.md`](../../RUNBOOK.md) ("Statusline Capture"); until then the
utilization gauges show *No data*.

---

## Troubleshooting

**Prometheus target is DOWN.** Prometheus can't reach `/metrics`. In Route A the
target is `web:8080` (in-network); confirm `docker compose ps` shows `web` up. In
Route B, curl the exact `host:port` from where Prometheus runs — a firewall or a
`127.0.0.1`-only bind (`cus serve --host 127.0.0.1`) will block a remote scrape;
bind `--host 0.0.0.0` if Prometheus is on another host.

**Dashboard panels all say "No data".** Either the scrape isn't landing (check
the target is UP and run the PromQL `cus_up` in Explore), or the datasource
variable isn't pointing at the right Prometheus (top-left **Prometheus**
dropdown on the dashboard).

**Values are zero / stale.** The data is a periodic snapshot. Zero means nothing
ingested yet (`cus_db_available` will be 0 if the DB file is missing). Re-ingest
(`cus ingest …` or let the worker run) and the gauges step up on the next scrape.

**"Over time" panels are short.** Expected — Prometheus only has history from
when it started scraping. They fill in as time passes.

**Grafana on :3000 or Prometheus on :9090 clashes with something.** Change the
left side of the `ports:` mapping in `docker-compose.yml` (Route A). The app's
own port is `8765` (also remappable there).
