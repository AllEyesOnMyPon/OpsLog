#!/usr/bin/env python3

import argparse
import base64
import hashlib
import hmac
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def canonical(method: str, path: str, body_sha_hex: str, ts_iso: str, nonce: str | None) -> bytes:
    parts = [method.upper(), path or "/", body_sha_hex, ts_iso]
    if nonce is not None:
        parts.append(nonce)
    return ("\n".join(parts)).encode("utf-8")


def sign(secret: str, msg: bytes) -> bytes:
    return hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).digest()


def parse_offset(spec: str) -> timedelta:
    if not spec:
        return timedelta(0)
    sign_mult = 1
    s = spec.strip()
    if s[0] in "+-":
        if s[0] == "-":
            sign_mult = -1
        s = s[1:]
    num = "".join(ch for ch in s if ch.isdigit())
    unit = s[len(num) :].lower() or "s"
    qty = int(num or "0")
    match unit:
        case "s" | "sec" | "secs" | "second" | "seconds":
            return timedelta(seconds=qty * sign_mult)
        case "m" | "min" | "mins" | "minute" | "minutes":
            return timedelta(minutes=qty * sign_mult)
        case "h" | "hr" | "hrs" | "hour" | "hours":
            return timedelta(hours=qty * sign_mult)
        case _:
            raise ValueError(f"Unsupported ts-offset unit: {spec!r}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Sign HMAC headers for LogOps gateway")
    ap.add_argument("api_key")
    ap.add_argument("secret")
    ap.add_argument("method")
    ap.add_argument("url")
    ap.add_argument("body", nargs="?")  # ignored if --body-file provided
    ap.add_argument("--body-file", default=None)
    ap.add_argument("--nonce", nargs="?", const="__AUTO__")
    ap.add_argument("--ts", default=None)
    ap.add_argument("--ts-offset", default=None)
    ap.add_argument("--one-per-line", dest="one_per_line", action="store_true")
    args = ap.parse_args()

    # BODY BYTES — prefer --body-file
    if args.body_file:
        with open(args.body_file, "rb") as f:
            body = f.read()
    else:
        body = (args.body or "").encode("utf-8")

    body_sha_hex = sha256_hex(body)

    # TIMESTAMP (UTC, ISO Z)
    if args.ts:
        if args.ts.endswith("Z"):
            ts = datetime.strptime(args.ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
        else:
            ts = datetime.fromisoformat(args.ts)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)
    else:
        ts = datetime.now(UTC)
    if args.ts_offset:
        ts += parse_offset(args.ts_offset)
    ts_iso = ts.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    # PATH from URL (bez query)
    u = urlparse(args.url)
    path = u.path or "/"

    # NONCE
    if args.nonce is None:
        nonce = None
    elif args.nonce == "__AUTO__":
        nonce = hashlib.sha256(f"{ts_iso}-{len(body)}".encode()).hexdigest()[:32]
    else:
        nonce = args.nonce

    # SIGN
    canon = canonical(args.method, path, body_sha_hex, ts_iso, nonce)
    signature_b64 = b64(sign(args.secret, canon))

    headers = [
        ("X-Api-Key", args.api_key),
        ("X-Timestamp", ts_iso),
        ("X-Content-SHA256", body_sha_hex),
    ]
    if nonce is not None:
        headers.append(("X-Nonce", nonce))
    headers.append(("X-Signature", signature_b64))

    if args.one_per_line:
        print(" ".join(f'-H "{k}: {v}"' for k, v in headers))
    else:
        for k, v in headers:
            print(f"{k}: {v}")


if __name__ == "__main__":
    main()
