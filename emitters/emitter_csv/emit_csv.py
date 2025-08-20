import argparse
import random
import time
import requests
from io import StringIO

URL = "http://127.0.0.1:8080/v1/logs"

LEVELS = ["DEBUG", "INFO", "WARN", "ERROR"]

def make_row(i: int, full: bool = True) -> str:
    ts = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    lvl = random.choice(LEVELS)
    msg = f"csv event #{i}"
    if full:
        return f'{ts},{lvl},"{msg}"'
    else:
        # brak ts i/lub level żeby sprawdzić normalizację
        return f',,{msg}'

def build_csv(n: int, partial_ratio: float) -> str:
    out = StringIO()
    out.write("ts,level,msg\n")  # nagłówek
    for i in range(1, n + 1):
        full = random.random() > partial_ratio
        out.write(make_row(i, full=full) + "\n")
    return out.getvalue()

def main(n: int, partial_ratio: float):
    csv_body = build_csv(n, partial_ratio)
    r = requests.post(
        URL,
        data=csv_body.encode("utf-8"),
        headers={"Content-Type": "text/csv"},
        timeout=5,
    )
    print("status:", r.status_code)
    print("body:", r.text)

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Emit CSV logs (ts,level,msg) to the gateway.")
    ap.add_argument("-n", "--num", type=int, default=10, help="liczba wierszy")
    ap.add_argument("--partial-ratio", type=float, default=0.3, help="odsetek uboższych wierszy (0–1)")
    args = ap.parse_args()
    main(args.num, args.partial_ratio)
