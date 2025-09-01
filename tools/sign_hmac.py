#!/usr/bin/env python3
import sys
import hmac
import base64
import hashlib
import uuid
import argparse
from urllib.parse import urlparse
from datetime import datetime, timezone, timedelta


def iso_now(offset_sec: int = 0) -> str:
    dt = datetime.now(timezone.utc) + timedelta(seconds=offset_sec)
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def path_with_query(url: str) -> str:
    p = urlparse(url)
    path = p.path or "/"
    return path + (("?" + p.query) if p.query else "")


def sha256_hex(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sign_b64(secret: str, canonical: bytes) -> str:
    mac = hmac.new(secret.encode("utf-8"), canonical, hashlib.sha256).digest()
    return base64.b64encode(mac).decode("ascii")


def main() -> int:
    ap = argparse.ArgumentParser(
        description='Emituje nagłówki HMAC jako ciąg -H "K: V" ... do użycia z curl.'
    )
    ap.add_argument("api_key")
    ap.add_argument("secret")
    ap.add_argument("method")
    ap.add_argument("url")
    ap.add_argument("body", nargs="?", default="{}")
    ap.add_argument("--nonce", action="store_true", help="dodaj X-Nonce")
    ap.add_argument("--ts-offset", type=int, default=0, help="przesunięcie sekund względem teraz (np. -1200)")
    ap.add_argument("--ts", type=str, default=None, help="jawny ISO8601 (np. 2025-08-27T04:10:00Z)")
    ap.add_argument("--body-file", type=str, default=None, help="czytaj body z pliku (do podpisu i curl)")
    ap.add_argument("--one-per-line", action="store_true", help="drukuj każdy nagłówek w osobnej linii")
    args = ap.parse_args()

    if args.body_file:
        with open(args.body_file, "rb") as fh:
            body_bytes = fh.read()
    else:
        body_bytes = args.body.encode("utf-8")

    body_hash = sha256_hex(body_bytes)
    ts = args.ts if args.ts else iso_now(args.ts_offset)

    canonical = "\n".join([
        args.method.upper(),
        path_with_query(args.url),
        ts,
        body_hash,
    ]).encode("utf-8")

    signature = sign_b64(args.secret, canonical)

    headers = [
        ("X-Api-Key", args.api_key),
        ("X-Timestamp", ts),
        ("X-Content-SHA256", body_hash),
        ("X-Signature", signature),
    ]
    if args.nonce:
        headers.append(("X-Nonce", uuid.uuid4().hex))

    if args.one_per_line:
        for k, v in headers:
            print(f'-H "{k}: {v}"')
    else:
        print(" ".join(f'-H "{k}: {v}"' for k, v in headers))
    return 0


if __name__ == "__main__":
    sys.exit(main())
