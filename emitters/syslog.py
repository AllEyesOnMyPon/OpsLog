#!/usr/bin/env python3
import argparse
import json as pyjson
import os
import random
import re
import socket
import time
from collections import Counter

from emitters.common.http_client import IngestClient, pace_interval, sleep_with_jitter

HOST = socket.gethostname()
APP = "web"
LEVELS = ["DEBUG", "INFO", "WARN", "ERROR"]
LEVEL_RE = re.compile(r"\b(DEBUG|INFO|WARN|ERROR)\b")


def sys_ts() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def make_line(i: int, full: bool = True) -> str:
    lvl = random.choice(LEVELS)
    base = f"{sys_ts()} {lvl} {HOST} {APP}[{random.randint(1000,9999)}]: request served #{i}"
    if not full:
        base = f"{sys_ts()} request served #{i}"
    return (
        base + f" user=user{i}@example.com ip=83.11.{random.randint(0,255)}.{random.randint(0,255)}"
    )


def build_payload(n: int, partial_ratio: float) -> tuple[str, Counter]:
    lines = []
    level_counts = Counter()
    for i in range(1, n + 1):
        full = random.random() > partial_ratio
        line = make_line(i, full=full)
        lines.append(line)
        m = LEVEL_RE.search(line)
        if m:
            level_counts[m.group(1)] += 1
    return "\n".join(lines) + "\n", level_counts


def main():
    ap = argparse.ArgumentParser(description="Syslog-like lines emitter")
    ap.add_argument(
        "--ingest-url",
        default=os.getenv("ENTRYPOINT_URL", "http://127.0.0.1:8081/ingest"),
        help="Endpoint wejściowy (domyślnie AuthGW)",
    )
    ap.add_argument("--scenario-id", required=True)
    ap.add_argument("--emitter", default="syslog")
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
    cli.set_content_type("text/plain")
    interval = pace_interval(args.eps, args.batch_size)
    end = time.time() + args.duration
    sent = 0

    while time.time() < end:
        payload, _ = build_payload(args.batch_size, args.partial_ratio)
        cli.post_bytes(payload.encode("utf-8"))
        sent += args.batch_size
        sleep_with_jitter(interval, args.jitter_ms)

    print("SC_STAT " + pyjson.dumps({"sent": sent}))


if __name__ == "__main__":
    main()
