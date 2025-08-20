import argparse
import random
import socket
import time
from typing import Dict, Any, List

import requests

URL = "http://127.0.0.1:8080/v1/logs"
SERVICE = "emitter-json"
ENV = "dev"
HOST = socket.gethostname()

LEVELS = ["debug", "info", "warning", "error", "fatal"]

def make_log(i: int, full: bool = True) -> Dict[str, Any]:
    """
    'Server-style' ustrukturyzowany JSON – jak typowy log aplikacyjny.
    """
    base: Dict[str, Any] = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),  # iso-ish; gateway na razie przepuszcza string
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
            "method": random.choice(["GET","POST","PUT"]),
            "latency_ms": random.randint(5, 500),
            "version": "1.0.0",
        },
    }
    if not full:
        # wersja „ułomna”: usuń timestamp i level, żeby sprawdzić normalizację i liczniki
        base.pop("timestamp", None)
        base.pop("level", None)
    return base

def main(n: int, partial_ratio: float):
    batch: List[Dict[str, Any]] = []
    for i in range(1, n + 1):
        full = random.random() > partial_ratio
        batch.append(make_log(i, full=full))
    r = requests.post(URL, json=batch, timeout=5)
    print("status:", r.status_code)
    print("body:", r.text)

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Emit structured JSON logs to the gateway.")
    ap.add_argument("-n", "--num", type=int, default=10, help="liczba logów w batchu")
    ap.add_argument("--partial-ratio", type=float, default=0.3,
                    help="odsetek logów z brakami (0.0–1.0)")
    args = ap.parse_args()
    main(n=args.num, partial_ratio=args.partial_ratio)
