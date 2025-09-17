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

HOST = socket.gethostname()
LEVEL_WORDS = ["debug", "info", "warning", "warn", "error", "fatal", "trace"]
MSG_WORDS = ["ok", "fail", "timeout", "retry", "db", "cache", "http", "queue", "auth", "io"]
KEY_ALIASES = [
    ("message", "msg", "log", "text"),
    ("level", "lvl", "severity"),
    ("timestamp", "ts", "time"),
]
EXTRA_KEYS = [
    "userId",
    "user_email",
    "client_ip",
    "path",
    "method",
    "durationMs",
    "env",
    "service",
    "meta",
]


def maybe(prob: float) -> bool:
    import random as _r

    return _r.random() < prob


def random_ts() -> str:
    if maybe(0.8):
        return time.strftime("%Y-%m-%dT%H:%M:%S%z")
    return f"not-a-timestamp-{random.randint(100,999)}"


def random_level() -> Any:
    choice = random.choice(LEVEL_WORDS)
    if maybe(0.15):
        return random.randint(0, 5)
    if maybe(0.1):
        return True
    return choice


def random_msg(i: int) -> Any:
    base = f"{random.choice(MSG_WORDS)} event #{i}"
    if maybe(0.2):
        return {"nested": base, "code": random.randint(100, 599)}
    if maybe(0.1):
        return [base, "extra", random.randint(1, 9)]
    return base


def random_alias_key(primary: str) -> str:
    for group in KEY_ALIASES:
        if primary in group:
            return random.choice(group)
    return primary


def random_extra_fields(rec: dict[str, Any], max_extra: int = 3) -> None:
    for _ in range(random.randint(0, max_extra)):
        k = random.choice(EXTRA_KEYS)
        if k in rec:
            continue
        if k == "user_email":
            v = f"user{random.randint(1,999)}@example.com"
        elif k == "client_ip":
            v = f"10.{random.randint(0,255)}.{random.randint(0,255)}.{random.randint(0,255)}"
        elif k == "durationMs":
            v = random.randint(1, 1500)
        elif k == "method":
            v = random.choice(["GET", "POST", "PUT", "DELETE"])
        elif k == "env":
            v = random.choice(["dev", "stg", "prod"])
        elif k == "meta":
            v = {"traceId": f"tr-{random.randint(1000,9999)}"}
        else:
            v = f"val-{random.randint(100,999)}"
        rec[k] = v


def make_noise_record(i: int, chaos: float) -> dict[str, Any]:
    rec: dict[str, Any] = {}
    if maybe(1.0 - chaos):
        rec[random_alias_key("timestamp")] = random_ts()
    if maybe(1.0 - chaos / 2):
        rec[random_alias_key("level")] = random_level()
    if maybe(1.0 - chaos / 3):
        rec[random_alias_key("message")] = random_msg(i)
    random_extra_fields(rec, max_extra=3)
    if all(k not in rec for k in ("message", "msg", "log")) and maybe(chaos / 2):
        rec["log"] = (
            f"{time.strftime('%Y-%m-%d %H:%M:%S')} ??? {HOST} app[{random.randint(1000,9999)}]: noise #{i}"
        )
    return rec


def main():
    ap = argparse.ArgumentParser(description="Noise emitter (chaotic JSON)")
    ap.add_argument(
        "--ingest-url",
        default=os.getenv("ENTRYPOINT_URL", "http://127.0.0.1:8081/ingest"),
        help="Endpoint wejściowy (domyślnie AuthGW)",
    )
    ap.add_argument("--scenario-id", required=True)
    ap.add_argument("--emitter", default="noise")
    ap.add_argument("--eps", type=int, default=10)
    ap.add_argument("--duration", type=int, default=60)
    ap.add_argument("--batch-size", type=int, default=10)
    ap.add_argument("--jitter-ms", type=int, default=0)
    ap.add_argument("--chaos", type=float, default=0.5)
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
            rec = make_noise_record(sent + i + 1, args.chaos)
            lvl = rec.get("level") or rec.get("lvl") or rec.get("severity")
            if isinstance(lvl, str):
                level_counts[lvl.upper()] += 1
            batch.append(rec)
        cli.post_json(batch)
        sent += len(batch)
        sleep_with_jitter(interval, args.jitter_ms)

    print("SC_STAT " + pyjson.dumps({"sent": sent}))


if __name__ == "__main__":
    main()
