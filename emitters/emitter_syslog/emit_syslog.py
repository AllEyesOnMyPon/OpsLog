import argparse
import random
import socket
import time
import requests
from collections import Counter
import json, re
import os
URL = "http://127.0.0.1:8080/v1/logs"

HOST = socket.gethostname()

APP  = "web"

LEVELS = ["DEBUG", "INFO", "WARN", "ERROR"]

LEVEL_RE = re.compile(r'\b(DEBUG|INFO|WARN|ERROR)\b')

SCENARIO = os.environ.get("LOGOPS_SCENARIO")

def sys_ts() -> str:
    # syslog-like (prosty, czytelny): "YYYY-mm-dd HH:MM:SS"
    return time.strftime("%Y-%m-%d %H:%M:%S")

def make_line(i: int, full: bool = True) -> str:
    lvl = random.choice(LEVELS)
    base = f"{sys_ts()} {lvl} {HOST} {APP}[{random.randint(1000,9999)}]: request served #{i}"
    if not full:
        # zasymuluj „ubogą” linię (bez poziomu i hosta)
        base = f"{sys_ts()} request served #{i}"
    # dorzuć trochę atrybutów (nieparsowane, ale stanowią „szum”)
    return base + f" user=user{i}@example.com ip=83.11.{random.randint(0,255)}.{random.randint(0,255)}"

def main(n: int, partial_ratio: float, seed: int | None):
    if seed is not None:
        random.seed(seed)

    lines = []
    level_counts = Counter()
    for i in range(1, n + 1):
        full = random.random() > partial_ratio
        line = make_line(i, full=full)
        lines.append(line)
        m = LEVEL_RE.search(line)
        if m:
            level_counts[m.group(1)] += 1

    payload = "\n".join(lines) + "\n"

    headers = {"Content-Type": "text/plain", "X-Emitter": "emitter_syslog"}
    scenario = os.environ.get("LOGOPS_SCENARIO")
    if scenario:
        headers["X-Scenario"] = scenario

    r = requests.post(URL, data=payload.encode("utf-8"), headers=headers, timeout=5)
    print("status:", r.status_code)
    print("body:", r.text)
    print("SC_STAT " + json.dumps({"level_counts": dict(level_counts)}))

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Emit syslog-like text lines to the gateway.")
    ap.add_argument("-n", "--num", type=int, default=10, help="liczba linii logów")
    ap.add_argument("--partial-ratio", type=float, default=0.3, help="odsetek uboższych linii (0.0–1.0)")
    ap.add_argument("--seed", type=int, default=None, help="seed RNG dla powtarzalności")
    args = ap.parse_args()
    main(args.num, args.partial_ratio, args.seed)
