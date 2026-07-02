from __future__ import annotations

import argparse
import os
import socket
import sys

from .db import connect, init_db
from .ingest import ingest_dir, reprice_events
from .pricing import load_prices


def _cmd_ingest(args: argparse.Namespace) -> int:
    conn = connect(args.db)
    try:
        init_db(conn)
        result = ingest_dir(conn, args.projects_dir, args.machine_id)
    finally:
        conn.close()
    print(
        "ingest: "
        f"files={result['files']} events={result['events']} "
        f"tool_uses={result['tool_uses']} skipped={result['skipped']} "
        f"bytes_read={result['bytes_read']} unpriced={result['unpriced']} "
        f"cost_usd={result['cost_usd']:.12f}"
    )
    return 0


def _cmd_pull(args: argparse.Namespace) -> int:
    from .config import load_config
    from .pull import pull_and_ingest

    config = load_config(args.config)
    conn = connect(config.central.db_path)
    try:
        init_db(conn)
        result = pull_and_ingest(conn, config)
    finally:
        conn.close()

    overall = result["overall"]
    print(
        "pull: "
        f"files={overall['files']} events={overall['events']} "
        f"tool_uses={overall['tool_uses']} skipped={overall['skipped']} "
        f"bytes_read={overall['bytes_read']} unpriced={overall['unpriced']} "
        f"cost_usd={overall['cost_usd']:.12f} errors={result['errors']}"
    )
    for machine_id, stats in result["machines"].items():
        if "error" in stats:
            print(f"  {machine_id}: error={stats['error']}")
        else:
            print(
                f"  {machine_id}: files={stats['files']} events={stats['events']} "
                f"tool_uses={stats['tool_uses']} skipped={stats['skipped']}"
            )
    return 1 if result["errors"] else 0


def _cmd_doctor(args: argparse.Namespace) -> int:
    from .doctor import load_config_for_doctor, run_doctor

    config, error = load_config_for_doctor(args.config)
    if error is not None:
        print(error, file=sys.stderr)
        return 1

    assert config is not None
    result = run_doctor(config)
    print(f"{'Machine':<20} {'Status':<6} Reason")
    print(f"{'-' * 20} {'-' * 6} {'-' * 6}")
    for check in result.checks:
        print(f"{check.machine_id:<20} {check.status:<6} {check.reason}")
    return 1 if result.failed else 0


def _cmd_reprice(args: argparse.Namespace) -> int:
    conn = connect(args.db)
    try:
        init_db(conn)
        prices = load_prices(args.litellm)
        result = reprice_events(conn, prices=prices)
    finally:
        conn.close()
    print(
        "reprice: "
        f"priced={result['priced']} unpriced={result['unpriced']} "
        f"cost_usd={result['cost_usd']:.12f}"
    )
    return 0


def _cmd_stats(args: argparse.Namespace) -> int:
    conn = connect(args.db)
    try:
        init_db(conn)
        totals = conn.execute(
            """
            SELECT
                COUNT(*) AS events,
                COALESCE(SUM(input_tokens), 0) AS input_tokens,
                COALESCE(SUM(output_tokens), 0) AS output_tokens,
                COALESCE(SUM(cache_creation_tokens), 0) AS cache_creation_tokens,
                COALESCE(SUM(cache_read_tokens), 0) AS cache_read_tokens,
                COALESCE(SUM(cost_usd), 0) AS cost_usd,
                SUM(CASE WHEN cost_usd IS NULL THEN 1 ELSE 0 END) AS unpriced
            FROM events
            """
        ).fetchone()
        sessions = conn.execute("SELECT COUNT(*) AS count FROM sessions").fetchone()["count"]
        print(f"events: {totals['events']}")
        print(f"sessions: {sessions}")
        print(f"input_tokens: {totals['input_tokens']}")
        print(f"output_tokens: {totals['output_tokens']}")
        print(f"cache_creation_tokens: {totals['cache_creation_tokens']}")
        print(f"cache_read_tokens: {totals['cache_read_tokens']}")
        print(f"cost_usd: {totals['cost_usd']:.12f}")
        print(f"unpriced: {totals['unpriced']}")
        print("models:")
        for row in conn.execute(
            "SELECT COALESCE(model, '<unknown>') AS model, COUNT(*) AS count FROM events GROUP BY model ORDER BY count DESC, model"
        ):
            print(f"  {row['model']}: {row['count']}")
    finally:
        conn.close()
    return 0


def _cmd_serve(args: argparse.Namespace) -> int:
    os.environ["CUS_DB"] = args.db
    import uvicorn

    uvicorn.run("cus.web.app:app", host=args.host, port=args.port)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cus")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ingest = subparsers.add_parser("ingest")
    ingest.add_argument("--projects-dir", required=True)
    ingest.add_argument("--db", required=True)
    ingest.add_argument("--machine-id", default=socket.gethostname())
    ingest.set_defaults(func=_cmd_ingest)

    pull = subparsers.add_parser("pull")
    pull.add_argument("--config", required=True)
    pull.set_defaults(func=_cmd_pull)

    doctor = subparsers.add_parser("doctor")
    doctor.add_argument("--config", required=True)
    doctor.set_defaults(func=_cmd_doctor)

    reprice = subparsers.add_parser("reprice")
    reprice.add_argument("--db", required=True)
    reprice.add_argument("--litellm")
    reprice.set_defaults(func=_cmd_reprice)

    stats = subparsers.add_parser("stats")
    stats.add_argument("--db", required=True)
    stats.set_defaults(func=_cmd_stats)

    serve = subparsers.add_parser("serve")
    serve.add_argument("--db", default="./data/cus.db")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8080)
    serve.set_defaults(func=_cmd_serve)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
