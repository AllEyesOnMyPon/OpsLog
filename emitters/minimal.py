#!/usr/bin/env python3
import argparse
import json as pyjson
import os
import time
from collections import Counter

from emitters.common.http_client import IngestClient, pace_interval, sleep_with_jitter


def make_batch(n: int) -> list[dict]:
    return [{"msg": f"minimal #{i}"} for i in range(1, n + 1)]


def main():
    ap = argparse.ArgumentParser(description="Minimal emitter (only msg)")
    ap.add_argument(
        "--ingest-url",
        default=os.getenv("ENTRYPOINT_URL", "http://127.0.0.1:8081/ingest"),
        help="Endpoint wejściowy (domyślnie AuthGW)",
    )
    ap.add_argument("--scenario-id", required=True)
    ap.add_argument("--emitter", default="minimal")
    ap.add_argument("--eps", type=int, default=10)
    ap.add_argument("--duration", type=int, default=60)
    ap.add_argument("--batch-size", type=int, default=10)
    ap.add_argument("--jitter-ms", type=int, default=0)
    args = ap.parse_args()

    cli = IngestClient(args.ingest_url, args.emitter, args.scenario_id)
    interval = pace_interval(args.eps, args.batch_size)
    end = time.time() + args.duration
    sent = 0

    while time.time() < end:
        batch = make_batch(args.batch_size)
        cli.post_json(batch)
        sent += len(batch)
        sleep_with_jitter(interval, args.jitter_ms)

    level_counts = Counter({"INFO": sent})
    print("SC_STAT " + pyjson.dumps({"sent": sent, "level_counts": dict(level_counts)}))


if __name__ == "__main__":
    main()
