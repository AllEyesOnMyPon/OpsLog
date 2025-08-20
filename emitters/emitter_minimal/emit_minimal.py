import argparse
import requests
from typing import List, Dict

URL = "http://127.0.0.1:8080/v1/logs"

def make_batch(n: int) -> List[Dict]:
    return [{"msg": f"minimal #{i}"} for i in range(1, n + 1)]

def main(n: int):
    batch = make_batch(n)
    r = requests.post(URL, json=batch, timeout=5)
    print("status:", r.status_code)
    print("body:", r.text)

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Emit minimal logs (only 'msg').")
    ap.add_argument("-n", "--num", type=int, default=10, help="liczba logów w batchu")
    args = ap.parse_args()
    main(args.num)
