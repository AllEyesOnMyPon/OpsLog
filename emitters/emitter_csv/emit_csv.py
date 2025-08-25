import argparse
import random
import time
import requests
from io import StringIO
from collections import Counter
import json
import os

URL = "http://127.0.0.1:8080/v1/logs"

LEVELS = ["DEBUG", "INFO", "WARN", "ERROR"]

SCENARIO = os.environ.get("LOGOPS_SCENARIO")

def make_row(i: int, full: bool = True) -> tuple[str, str | None, str]:
    ts = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    lvl = random.choice(LEVELS)
    msg = f"csv event #{i}"
    if full:
        return f'{ts},{lvl},"{msg}"', lvl, msg
    else:
        # brak ts i/lub level żeby sprawdzić normalizację
        return f',,{msg}', None, msg

def build_csv(n: int, partial_ratio: float) -> tuple[str, Counter]:
    out = StringIO()
    out.write("ts,level,msg\n")  # nagłówek
    level_counts = Counter()
    for i in range(1, n + 1):
        full = random.random() > partial_ratio
        row, lvl, _ = make_row(i, full=full)
        if lvl:
            level_counts[lvl] += 1
        out.write(row + "\n")
    return out.getvalue(), level_counts

def main(n: int, partial_ratio: float, seed: int | None):
    if seed is not None:
        random.seed(seed)
    csv_body, level_counts = build_csv(n, partial_ratio)

    # bazowe nagłówki
    headers = {
        "Content-Type": "text/csv",
        "X-Emitter": "emitter_csv",
    }

    # jeśli ustawiono LOGOPS_SCENARIO w środowisku → dodaj nagłówek
    scenario = os.environ.get("LOGOPS_SCENARIO")
    if scenario:
        headers["X-Scenario"] = scenario

    r = requests.post(
        URL,
        data=csv_body.encode("utf-8"),
        headers=headers,
        timeout=5,
    )

    print("status:", r.status_code)
    print("body:", r.text)
    print("SC_STAT " + json.dumps({"level_counts": dict(level_counts)}))

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Emit CSV logs (ts,level,msg) to the gateway.")
    ap.add_argument("-n", "--num", type=int, default=10, help="liczba wierszy")
    ap.add_argument("--partial-ratio", type=float, default=0.3, help="odsetek uboższych wierszy (0–1)")
    ap.add_argument("--seed", type=int, default=None, help="seed RNG dla powtarzalności")
    args = ap.parse_args()
    main(args.num, args.partial_ratio, args.seed)
