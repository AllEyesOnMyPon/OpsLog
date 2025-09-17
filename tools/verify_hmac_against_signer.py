#!/usr/bin/env python3
import argparse
import base64
import hashlib
import hmac
import os
import re
import sys
import urllib.parse

# akceptujemy oba style: X-Api-* (Twój) i X-Logops-* (starszy)
PATTERNS = [
    {  # Twój obecny styl
        "key": re.compile(r"(?i)^\s*X-Api-Key\s*:\s*(.+)\s*$"),
        "ts": re.compile(r"(?i)^\s*X-Timestamp\s*:\s*([0-9T:\-]+Z)\s*$"),  # ISO8601 Zulu
        "nonce": re.compile(r"(?i)^\s*X-Nonce\s*:\s*([0-9a-fA-F]+)\s*$"),
        "body_sha": re.compile(r"(?i)^\s*X-Content-SHA256\s*:\s*([0-9a-fA-F]{64})\s*$"),
        "sig_b64": re.compile(r"(?i)^\s*X-Signature\s*:\s*([A-Za-z0-9+/=]+)\s*$"),
        "style": "api_iso_b64",
    },
    {  # starszy styl (na wypadek gdybyś go użył gdzie indziej)
        "key": re.compile(r"(?i)^\s*X-Logops-Key\s*:\s*(.+)\s*$"),
        "ts": re.compile(r"(?i)^\s*X-Logops-Ts\s*:\s*(\d+)\s*$"),  # epoch seconds
        "nonce": re.compile(r"(?i)^\s*X-Logops-Nonce\s*:\s*([0-9a-fA-F]+)\s*$"),
        "sig_hex": re.compile(r"(?i)^\s*X-Logops-Signature\s*:\s*([0-9a-fA-F]{64})\s*$"),
        "style": "logops_epoch_hex",
    },
]


def canonical_path(url: str) -> str:
    p = urllib.parse.urlparse(url)
    return (p.path or "/") + (("?" + p.query) if p.query else "")


def sha256_hex(b: bytes) -> str:
    return hashlib.sha256(b or b"").hexdigest()


def calc_sig(secret: str, method: str, url: str, body: bytes, ts: str, nonce: str):
    can = "\n".join([method.upper(), canonical_path(url), sha256_hex(body), ts, nonce]).encode(
        "utf-8"
    )
    digest = hmac.new(secret.encode("utf-8"), can, hashlib.sha256).digest()
    return digest, can.decode("utf-8")


def parse_headers_from_stdin():
    raw = sys.stdin.read()
    hdrs = [tok for tok in re.findall(r'-H\s+"([^"]+)"', raw)]
    if not hdrs:
        hdrs = [line.strip() for line in raw.splitlines() if line.strip()]
    return hdrs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--method", default="POST")
    ap.add_argument("--body-file", required=True)
    args = ap.parse_args()

    secret = os.environ.get("LOGOPS_SECRET")
    if not secret:
        print("ERR: LOGOPS_SECRET is not set", file=sys.stderr)
        sys.exit(2)

    hdrs = parse_headers_from_stdin()

    style = None
    ts = nonce = sig_hex = sig_b64 = body_sha_hdr = None

    for pat in PATTERNS:
        ts = nonce = sig_hex = sig_b64 = body_sha_hdr = None
        for h in hdrs:
            if pat.get("ts") and (m := pat["ts"].search(h)):
                ts = m.group(1).strip()
            if pat.get("nonce") and (m := pat["nonce"].search(h)):
                nonce = m.group(1).strip()
            if pat.get("sig_hex") and (m := pat["sig_hex"].search(h)):
                sig_hex = m.group(1).strip().lower()
            if pat.get("sig_b64") and (m := pat["sig_b64"].search(h)):
                sig_b64 = m.group(1).strip()
            if pat.get("body_sha") and (m := pat["body_sha"].search(h)):
                body_sha_hdr = m.group(1).strip().lower()

        # mamy kompletny zestaw dla danego stylu?
        if pat["style"] == "api_iso_b64" and ts and nonce and sig_b64:
            style = pat["style"]
            break
        if pat["style"] == "logops_epoch_hex" and ts and nonce and sig_hex:
            style = pat["style"]
            break

    if not style:
        print("ERR: could not parse required headers for any known style", file=sys.stderr)
        sys.exit(3)

    body = open(args.body_file, "rb").read()
    sig_bytes, can = calc_sig(secret, args.method, args.url, body, ts, nonce)

    if style == "api_iso_b64":
        calc_b64 = base64.b64encode(sig_bytes).decode("ascii")
        ok = calc_b64 == sig_b64
        print(("OK" if ok else "MISMATCH") + f" [{style}]")
        if body_sha_hdr and body_sha_hdr != sha256_hex(body):
            print("WARN: X-Content-SHA256 mismatch vs computed SHA256(body)")
        print(" provided (b64):", sig_b64)
        print(" computed (b64):", calc_b64)
    else:
        calc_hex = sig_bytes.hex()
        ok = calc_hex == sig_hex
        print(("OK" if ok else "MISMATCH") + f" [{style}]")
        print(" provided (hex):", sig_hex)
        print(" computed (hex):", calc_hex)

    print(" canonical:\n" + can)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
