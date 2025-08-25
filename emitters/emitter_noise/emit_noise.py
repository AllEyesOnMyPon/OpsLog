import argparse
import random
import socket
import time
from typing import Any, Dict, List, Optional
from collections import Counter
import json
import requests
import os

URL = "http://127.0.0.1:8080/v1/logs"

HOST = socket.gethostname()

LEVEL_WORDS = ["debug", "info", "warning", "warn", "error", "fatal", "trace"]

MSG_WORDS = ["ok", "fail", "timeout", "retry", "db", "cache", "http", "queue", "auth", "io"]

KEY_ALIASES = [
    ("message", "msg", "log", "text"),
    ("level", "lvl", "severity"),
    ("timestamp", "ts", "time"),
]

EXTRA_KEYS = ["userId", "user_email", "client_ip", "path", "method", "durationMs", "env", "service", "meta"]

SCENARIO = os.environ.get("LOGOPS_SCENARIO")

def maybe(prob: float) -> bool:
    return random.random() < prob

def random_ts() -> str:
    # czasem poprawny ISO, czasem „jakikolwiek” string
    if maybe(0.8):
        return time.strftime("%Y-%m-%dT%H:%M:%S%z")
    return f"not-a-timestamp-{random.randint(100,999)}"

def random_level() -> Any:
    # czasem poprawny string, czasem liczba/bool — żeby przetestować str() w normalizacji
    choice = random.choice(LEVEL_WORDS)
    if maybe(0.15):
        return random.randint(0, 5)
    if maybe(0.1):
        return True
    return choice

def random_msg(i: int) -> Any:
    base = f"{random.choice(MSG_WORDS)} event #{i}"
    if maybe(0.2):
        return {"nested": base, "code": random.randint(100, 599)}  # zagnieżdżony obiekt
    if maybe(0.1):
        return [base, "extra", random.randint(1, 9)]               # lista
    return base

def random_alias_key(primary: str) -> str:
    for group in KEY_ALIASES:
        if primary in group:
            return random.choice(group)
    return primary

def random_extra_fields(rec: Dict[str, Any], max_extra: int = 3) -> None:
    for _ in range(random.randint(0, max_extra)):
        k = random.choice(EXTRA_KEYS)
        if k in rec:
            continue
        if k in ("user_email",):
            v = f"user{random.randint(1,999)}@example.com"
        elif k in ("client_ip",):
            v = f"10.{random.randint(0,255)}.{random.randint(0,255)}.{random.randint(0,255)}"
        elif k in ("durationMs",):
            v = random.randint(1, 1500)
        elif k in ("method",):
            v = random.choice(["GET","POST","PUT","DELETE"])
        elif k in ("env",):
            v = random.choice(["dev","stg","prod"])
        elif k in ("meta",):
            v = {"traceId": f"tr-{random.randint(1000,9999)}"}
        else:
            v = f"val-{random.randint(100,999)}"
        rec[k] = v

def make_noise_record(i: int, chaos: float) -> Dict[str, Any]:
    rec: Dict[str, Any] = {}

    # losowo wybieramy, które „główne” pola w ogóle damy
    if maybe(1.0 - chaos):  # ts z pewnym prawdopodobieństwem nie pojawi się
        rec[random_alias_key("timestamp")] = random_ts()
    if maybe(1.0 - chaos/2):
        rec[random_alias_key("level")] = random_level()
    if maybe(1.0 - chaos/3):
        rec[random_alias_key("message")] = random_msg(i)

    # dorzućmy losowe dodatkowe pola
    random_extra_fields(rec, max_extra=3)

    # czasem „surowa” linia zamiast message
    if "message" not in rec and "msg" not in rec and "log" not in rec and maybe(chaos/2):
        rec["log"] = f"{time.strftime('%Y-%m-%d %H:%M:%S')} ??? {HOST} app[{random.randint(1000,9999)}]: noise #{i}"

    return rec

def main(n: int, chaos: float, seed: Optional[int]):
    if seed is not None:
        random.seed(seed)

    batch: List[Dict[str, Any]] = []
    level_counts = Counter()

    for i in range(1, n + 1):
        rec = make_noise_record(i, chaos)
        lvl = (rec.get("level") or rec.get("lvl") or rec.get("severity"))
        if isinstance(lvl, str):
            level_counts[lvl.upper()] += 1
        batch.append(rec)

    headers = {"X-Emitter": "emitter_noise"}
    scenario = os.environ.get("LOGOPS_SCENARIO")
    if scenario:
        headers["X-Scenario"] = scenario

    r = requests.post(URL, json=batch, headers=headers, timeout=10)
    print("status:", r.status_code)
    print("body:", r.text)
    print("SC_STAT " + json.dumps({"level_counts": dict(level_counts)}))

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Emit noisy/chaotic JSON records to test gateway normalization.")
    ap.add_argument("-n", "--num", type=int, default=20, help="liczba rekordów")
    ap.add_argument("--chaos", type=float, default=0.5, help="poziom chaosu 0.0–1.0 (więcej braków i dziwnych typów)")
    ap.add_argument("--seed", type=int, default=None, help="seed RNG dla powtarzalności")
    args = ap.parse_args()
    main(args.num, args.chaos, args.seed)
