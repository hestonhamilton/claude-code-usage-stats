# claude-usage-stats Runbook

## Overview

Use one central host on the LAN to run Docker Compose. The `worker` container is
the only SQLite writer: it pulls each remote machine's Claude data into staging
and ingests it. The `web` container is a reader that serves the dashboard.

## Central Host

Install the repo on the central host, then create config and key directories:

```sh
cp config/machines.example.toml config/machines.toml
mkdir -p keys && chmod 700 keys
```

Bring the stack up:

```sh
docker compose up --build -d
```

The dashboard listens on host port `8765`: `http://<host>:8765`. The SQLite DB
and staging area live in the Compose volumes mounted at the paths configured in
`config/machines.toml`.

## Deploy Key

Generate a read-only deploy key:

```sh
scripts/gen-deploy-key.sh --dir ./keys --name id_ed25519
```

Install the recommended restricted `authorized_keys` line printed by the script
on each remote. It uses `rrsync -ro ~/.claude` to confine the key to read-only
rsync under `~/.claude`. `rrsync` usually ships with rsync docs; the path varies
by distro.

Keep the private key in `./keys`. In `machines.toml`, set:

```toml
ssh_key = "/keys/id_ed25519"
```

That is the in-container path mounted by Compose.

## machines.toml

Fill one `[[machines]]` entry per source. For SSH sources, set `id`, `transport =
"ssh"`, `host`, `user`, `ssh_key`, `remote_path`, and optionally
`rate_limit_log`.

The `id` becomes `machine_id` in the database, so keep it stable.

Example:

```toml
[[machines]]
id = "workstation"
transport = "ssh"
host = "192.168.1.20"
user = "user"
ssh_key = "/keys/id_ed25519"
remote_path = "/home/user/.claude/projects"
rate_limit_log = "/home/user/.claude/rate-limits.jsonl"
```

## Statusline Capture

On each machine, patch the Claude Code statusline:

```sh
scripts/setup-statusline.sh --apply
```

Dry-run first by omitting `--apply`. If your statusline dotfile is shared, edit
it once, commit it, and sync it to each machine.

Rate-limit windows are per Anthropic account, not per machine. Snapshots from
all machines are merged into one account timeline and never summed.

## Verify

Run the checks from the central host:

```sh
cus doctor --config config/machines.toml
cus pull --config config/machines.toml
```

Open `http://<host>:8765`, then check `/plan` and `/highlights`.

## Grafana / Prometheus dashboard

To display usage & value in Grafana (headline API-equivalent value, subscription
ROI, cache savings, plan utilization), the app exposes a Prometheus `/metrics`
endpoint. A complete **0 → working dashboard** runbook — both a fully
containerized route and a bring-your-own-stack route — lives in
[`deploy/grafana/README.md`](deploy/grafana/README.md).

## Troubleshooting

SSH failures usually mean the deploy key path, `authorized_keys` line, host, or
user is wrong. Test with the exact key and remote from `machines.toml`.

Rsync permission errors usually mean the restricted `rrsync` root does not
match the configured remote path, or `rrsync` is not installed where the remote
SSH session can run it.

Missing rate-limit logs are warnings until a Claude Code session runs with the
patched statusline.

SQLite WAL readers need access to the `-wal` and `-shm` sidecar files. Keep the
Compose topology as worker writer and web reader.

If port `8765` is already in use, change the left side of the web service port
mapping in `docker-compose.yml`.

## Rollback

Remove the managed statusline block:

```sh
scripts/setup-statusline.sh --remove --apply
```

Stop the stack:

```sh
docker compose down
```

Remove the deploy key line from each remote's `~/.ssh/authorized_keys`.
