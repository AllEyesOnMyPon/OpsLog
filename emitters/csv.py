#!/usr/bin/env python3
import argparse
import json as pyjson
import os
import random
import time
from collections import Counter
from io import StringIO

from emitters.common.http_client import IngestClient, pace_interval, sleep_with_jitter

LEVELS = ["DEBUG", "INFO", "WARN", "ERROR"]


def make_row(i: int, full: bool = True) -> tuple[str, str | None, str]:
    ts = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    lvl = random.choice(LEVELS)
    msg = f"csv event #{i}"
    if full:
        return f'{ts},{lvl},"{msg}"', lvl, msg
    else:
        return f",,{msg}", None, msg


def build_csv(n: int, partial_ratio: float) -> tuple[str, Counter]:
    out = StringIO()
    out.write("ts,level,msg\n")
    level_counts = Counter()
    for i in range(1, n + 1):
        full = random.random() > partial_ratio
        row, lvl, _ = make_row(i, full=full)
        if lvl:
            level_counts[lvl] += 1
        out.write(row + "\n")
    return out.getvalue(), level_counts


def main():
    ap = argparse.ArgumentParser(description="CSV emitter (ts,level,msg)")
    ap.add_argument(
        "--ingest-url",
        default=os.getenv("ENTRYPOINT_URL", "http://127.0.0.1:8081/ingest"),
        help="Endpoint wejściowy (domyślnie AuthGW)",
    )
    ap.add_argument("--scenario-id", required=True)
    ap.add_argument("--emitter", default="csv")
    ap.add_argument("--eps", type=int, default=10)
    ap.add_argument("--duration", type=int, default=60)
    ap.add_argument("--batch-size", type=int, default=10)
    ap.add_argument("--jitter-ms", type=int, default=0)
    ap.add_argument("--partial-ratio", type=float, default=0.3)
    ap.add_argument("--seed", type=int, default=None)
    args = ap.parse_args()

    if args.seed is not None:
        random.seed(args.seed)

    cli = IngestClient(args.ingest_url, args.emitter, args.scenario_id)
    cli.set_content_type("text/csv")
    interval = pace_interval(args.eps, args.batch_size)
    end = time.time() + args.duration
    sent = 0

    while time.time() < end:
        csv_body, _ = build_csv(args.batch_size, args.partial_ratio)
        cli.post_bytes(csv_body.encode("utf-8"))
        sent += args.batch_size
        sleep_with_jitter(interval, args.jitter_ms)

    print("SC_STAT " + pyjson.dumps({"sent": sent}))


if __name__ == "__main__":
    main()
