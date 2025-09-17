#!/usr/bin/env python3
import argparse
import json as pyjson
import os
import random
import socket
import time
from collections import Counter
from typing import Any

from emitters.common.http_client import IngestClient, pace_interval, sleep_with_jitter

LEVELS = ["debug", "info", "warning", "error", "fatal"]
SERVICE = "emitter-json"
ENV = "dev"
HOST = socket.gethostname()


def make_log(i: int, full: bool = True) -> dict[str, Any]:
    base: dict[str, Any] = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "level": random.choice(LEVELS),
        "message": f"request served #{i}",
        "service": SERVICE,
        "env": ENV,
        "host": HOST,
        "request_id": f"req-{i:06d}",
        "user_email": f"user{i}@example.com",
        "client_ip": f"83.11.{random.randint(0,255)}.{random.randint(0,255)}",
        "attrs": {
            "path": "/api/v1/resource",
            "method": random.choice(["GET", "POST", "PUT"]),
            "latency_ms": random.randint(5, 500),
            "version": "1.0.0",
        },
    }
    if not full:
        base.pop("timestamp", None)
        base.pop("level", None)
    return base


def main():
    ap = argparse.ArgumentParser(description="JSON emitter (structured logs)")
    ap.add_argument(
        "--ingest-url",
        default=os.getenv("ENTRYPOINT_URL", "http://127.0.0.1:8081/ingest"),
        help="Endpoint wejściowy (domyślnie AuthGW)",
    )
    ap.add_argument("--scenario-id", required=True)
    ap.add_argument("--emitter", default="json")
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
    interval = pace_interval(args.eps, args.batch_size)
    end = time.time() + args.duration
    sent = 0

    while time.time() < end:
        batch: list[dict[str, Any]] = []
        level_counts = Counter()
        for i in range(args.batch_size):
            full = random.random() > args.partial_ratio
            rec = make_log(sent + i + 1, full=full)
            lvl = rec.get("level")
            if isinstance(lvl, str):
                level_counts[lvl.upper()] += 1
            batch.append(rec)

        cli.post_json(batch)
        sent += len(batch)
        sleep_with_jitter(interval, args.jitter_ms)

    print("SC_STAT " + pyjson.dumps({"sent": sent}))


if __name__ == "__main__":
    main()
