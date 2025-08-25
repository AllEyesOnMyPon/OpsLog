import argparse
import requests
from typing import List, Dict
from collections import Counter
import json
import os

URL = "http://127.0.0.1:8080/v1/logs"

SCENARIO = os.environ.get("LOGOPS_SCENARIO")

def make_batch(n: int) -> List[Dict]:
    return [{"msg": f"minimal #{i}"} for i in range(1, n + 1)]

def main(n: int):
    batch = make_batch(n)

    headers = {"X-Emitter": "emitter_minimal"}
    scenario = os.environ.get("LOGOPS_SCENARIO")
    if scenario:
        headers["X-Scenario"] = scenario

    r = requests.post(URL, json=batch, headers=headers, timeout=5)
    print("status:", r.status_code)
    print("body:", r.text)

    # Minimal nie ma level — raportujemy jako INFO
    level_counts = Counter({"INFO": n})
    print("SC_STAT " + json.dumps({"level_counts": dict(level_counts)}))

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Emit minimal logs (only 'msg').")
    ap.add_argument("-n", "--num", type=int, default=10, help="liczba logów w batchu")
    args = ap.parse_args()
    main(args.num)
