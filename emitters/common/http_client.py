# emitters/common/http_client.py
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import random
import secrets
import time
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

import requests

# ── HMAC helpers (zgodne z tools/sign_hmac.py) ─────────────────────────────────


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data or b"").hexdigest()


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _iso_utc_now_z() -> str:
    # Dokładnie taki sam format jak w tools/sign_hmac.py: %Y-%m-%dT%H:%M:%SZ
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _canonical(
    method: str, path_no_query: str, body_sha_hex: str, ts_iso_z: str, nonce: str | None
) -> bytes:
    parts = [method.upper(), path_no_query or "/", body_sha_hex, ts_iso_z]
    if nonce is not None:
        parts.append(nonce)
    return ("\n".join(parts)).encode("utf-8")


def _hmac_headers(url: str, body: bytes, method: str = "POST") -> dict[str, str]:
    """
    Buduje nagłówki HMAC zgodne z tools/sign_hmac.py.
    - PATH w canonicalu to ścieżka BEZ query.
    - NONCE jest domyślnie dodawany; można go wyłączyć LOGOPS_DISABLE_NONCE=1.
    - Jeśli brak kluczy w ENV → zwracamy pusty dict (bez podpisu).
    """
    api_key = os.environ.get("LOGOPS_API_KEY")
    secret = os.environ.get("LOGOPS_SECRET")
    if not api_key or not secret:
        return {}  # brak podpisu = działa tylko na otwartych endpointach (np. 8080)

    ts_iso = _iso_utc_now_z()

    use_nonce = os.environ.get("LOGOPS_DISABLE_NONCE", "0") not in ("1", "true", "yes")
    nonce: str | None = secrets.token_hex(16) if use_nonce else None

    u = urlparse(url)
    path_no_query = u.path or "/"

    body_sha = _sha256_hex(body)
    canon = _canonical(method, path_no_query, body_sha, ts_iso, nonce)
    sig_b64 = _b64(hmac.new(secret.encode("utf-8"), canon, hashlib.sha256).digest())

    headers: dict[str, str] = {
        "X-Api-Key": api_key,
        "X-Timestamp": ts_iso,
        "X-Content-SHA256": body_sha,
        "X-Signature": sig_b64,
    }
    if nonce is not None:
        headers["X-Nonce"] = nonce
    return headers


# ── HTTP klient do emiterów ────────────────────────────────────────────────────


class IngestClient:
    """
    Prosty klient HTTP używany przez emitery.
    - Domyślnie Content-Type: application/json (można zmienić set_content_type).
    - Automatycznie dokleja X-Emitter i X-Scenario-Id.
    - Jeżeli w ENV są LOGOPS_API_KEY/LOGOPS_SECRET → podpisuje HMAC-em.
    """

    def __init__(self, url: str, emitter: str, scenario_id: str, timeout: float = 5.0):
        self.url = url
        self.base_headers: dict[str, str] = {
            "Content-Type": "application/json",
            "X-Emitter": emitter,
            "X-Scenario-Id": scenario_id,
        }
        self.timeout = timeout
        self._session = requests.Session()

    def set_content_type(self, value: str) -> None:
        self.base_headers["Content-Type"] = value

    def post_json(self, records: list[dict[str, Any]]) -> None:
        body = json.dumps(records, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        headers = dict(self.base_headers)
        headers.update(_hmac_headers(self.url, body, "POST"))
        self._session.post(
            self.url, headers=headers, data=body, timeout=self.timeout
        ).raise_for_status()

    def post_bytes(self, payload: bytes) -> None:
        headers = dict(self.base_headers)
        headers.update(_hmac_headers(self.url, payload, "POST"))
        self._session.post(
            self.url, headers=headers, data=payload, timeout=self.timeout
        ).raise_for_status()


# ── pacing helpers ─────────────────────────────────────────────────────────────


def pace_interval(eps: int, batch_size: int) -> float:
    eps = max(1, int(eps))
    b = max(1, int(batch_size))
    batches_per_sec = eps / b
    return 1.0 / batches_per_sec if batches_per_sec > 0 else 1.0


def sleep_with_jitter(base_seconds: float, jitter_ms: int) -> None:
    if jitter_ms <= 0:
        time.sleep(max(0.0, base_seconds))
        return
    jitter = random.uniform(-jitter_ms, jitter_ms) / 1000.0
    time.sleep(max(0.0, base_seconds + jitter))
