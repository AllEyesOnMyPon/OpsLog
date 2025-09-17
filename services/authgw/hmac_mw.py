# services/authgw/hmac_mw.py
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import time
from datetime import UTC, datetime
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

__all__ = ["HmacAuthMiddleware"]

logger = logging.getLogger("authgw.hmac")


def _debug_hmac() -> bool:
    import os

    v = os.getenv("AUTHGW_DEBUG_HMAC", "")
    return v not in ("", "0", "false", "False", "no", "NO")


def _parse_ts(ts: str) -> datetime | None:
    """Próbuje sparsować ISO8601; wspiera sufiks 'Z' i offsety."""
    try:
        if ts.endswith("Z"):
            # 2025-09-06T12:34:56Z
            return datetime.fromisoformat(ts[:-1]).replace(tzinfo=UTC)
        # 2025-09-06T12:34:56+00:00
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            # potraktuj jako UTC jeśli brak strefy
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    except Exception:
        return None


class HmacAuthMiddleware:
    """
    Canonical (zgodny z tools/sign_hmac.py):
      METHOD\nPATH\nSHA256_HEX(body)\nX-Timestamp\nX-Nonce

    X-Signature = base64( HMAC_SHA256(secret, canonical) )

    Dodatkowo:
    - weryfikacja X-Timestamp względem clock_skew_sec (UTC)
    - ochrona przed replay (nonce + Redis/in-memory)
    """

    def __init__(
        self,
        app,
        *,
        mode: str = "hmac",
        clients: dict[str, dict[str, Any]] | None = None,
        clock_skew_sec: int = 300,
        require_nonce: bool = True,
        nonce_store=None,
    ):
        self.app = app
        self.mode = (mode or "hmac").lower()
        self.clients = clients or {}
        self.clock_skew_sec = int(clock_skew_sec or 0)
        self.require_nonce = bool(require_nonce)
        self.nonce_store = nonce_store
        self._nonce_cache: dict[str, float] = {}

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        request = Request(scope, receive=receive)
        path = request.url.path

        # BYPASS dla sond/obserwacji i dokumentacji
        if path in (
            "/metrics",
            "/health",
            "/healthz",
            "/openapi.json",
            "/docs",
            "/redoc",
            "/docs/oauth2-redirect",
        ):
            return await self.app(scope, receive, send)

        if self.mode == "none":
            return await self.app(scope, receive, send)

        try:
            # 1) API key
            api_key: str | None = request.headers.get("x-api-key")
            if not api_key:
                return await JSONResponse({"error": "missing X-Api-Key"}, 401)(scope, receive, send)

            client = self.clients.get(api_key)
            if not client or not client.get("secret"):
                return await JSONResponse({"error": "invalid api key"}, 401)(scope, receive, send)

            if self.mode == "apikey":
                # w trybie apikey tylko uzupełniamy state
                self._populate_state(request, api_key, client, b"")
                return await self.app(scope, receive, send)

            # 2) HMAC headers
            ts = request.headers.get("x-timestamp")
            sign = request.headers.get("x-signature")
            body_hash_hdr = request.headers.get("x-content-sha256")
            nonce = request.headers.get("x-nonce")

            if not (ts and sign and body_hash_hdr):
                return await JSONResponse({"error": "missing hmac headers"}, 401)(
                    scope, receive, send
                )

            # 3) Timestamp skew
            dt = _parse_ts(ts)
            if dt is None:
                return await JSONResponse({"error": "bad X-Timestamp"}, 400)(scope, receive, send)
            now = datetime.now(UTC)
            if self.clock_skew_sec and abs((now - dt).total_seconds()) > self.clock_skew_sec:
                return await JSONResponse({"error": "timestamp skew"}, 401)(scope, receive, send)

            # 4) Nonce replay
            if self.require_nonce:
                if not nonce:
                    return await JSONResponse({"error": "missing X-Nonce"}, 401)(
                        scope, receive, send
                    )
                if await self._nonce_seen(api_key, nonce):
                    return await JSONResponse({"error": "nonce replay"}, 401)(scope, receive, send)

            # 5) Body + jego SHA256 (HEX)
            body = await request.body()
            body_sha256_hex = hashlib.sha256(body).hexdigest()
            if (body_hash_hdr or "").lower() != body_sha256_hex.lower():
                return await JSONResponse({"error": "bad X-Content-SHA256"}, 400)(
                    scope, receive, send
                )

            # 6) Canonical + podpis
            method = request.method.upper()
            path_only = request.url.path
            canonical = "\n".join([method, path_only, body_sha256_hex, ts, nonce or ""])
            expected_b64 = base64.b64encode(
                hmac.new(
                    client["secret"].encode("utf-8"), canonical.encode("utf-8"), hashlib.sha256
                ).digest()
            ).decode("ascii")

            if not hmac.compare_digest(sign, expected_b64):
                if _debug_hmac():
                    logger.error(
                        "HMAC mismatch\ncanonical:\n%s\nexpected:%s\nprovided:%s",
                        canonical,
                        expected_b64,
                        sign,
                    )
                return await JSONResponse({"error": "bad signature"}, 401)(scope, receive, send)

            # 7) zapamiętaj nonce
            if self.require_nonce:
                await self._nonce_remember(api_key, nonce, ttl=self.clock_skew_sec or 300)

            # 8) uzupełnij state i reinject body
            self._populate_state(request, api_key, client, body)

            async def receive_with_buffer(sent=None):
                if sent is None:
                    sent = [False]
                if not sent[0]:
                    sent[0] = True
                    return {"type": "http.request", "body": body, "more_body": False}
                return {"type": "http.request", "body": b"", "more_body": False}

            return await self.app(scope, receive_with_buffer, send)

        except Exception:
            logger.exception("HMAC middleware error")
            return await JSONResponse({"error": "internal auth error"}, 500)(scope, receive, send)

    # --- helpers ---

    def _populate_state(self, request: Request, api_key: str, client: dict[str, Any], body: bytes):
        emitter = client.get("emitter") or request.headers.get("x-emitter") or "unknown"

        # IP z gniazda albo X-Forwarded-For
        client_ip = None
        try:
            client_ip = (request.scope.get("client") or (None, None))[0]
        except Exception:
            client_ip = None
        client_ip = client_ip or request.headers.get("x-forwarded-for") or ""

        scenario_id = (
            request.headers.get("x-scenario-id") or request.headers.get("x-scenario") or None
        )

        request.state.api_key = api_key
        request.state.client = client
        request.state.emitter = emitter
        request.state.client_ip = client_ip
        request.state.scenario_id = scenario_id
        request.state.raw_body = body

    async def _nonce_seen(self, api_key: str, nonce: str) -> bool:
        key = f"hmac:nonce:{api_key}:{nonce}"
        if self.nonce_store:
            val = self.nonce_store.get(key)
            if callable(getattr(val, "__await__", None)):
                val = await val
            return val is not None
        now = time.time()
        for k, exp in list(self._nonce_cache.items()):
            if exp <= now:
                self._nonce_cache.pop(k, None)
        return key in self._nonce_cache

    async def _nonce_remember(self, api_key: str, nonce: str, ttl: int = 300):
        key = f"hmac:nonce:{api_key}:{nonce}"
        if self.nonce_store:
            setex = getattr(self.nonce_store, "setex", None)
            if setex:
                rv = setex(key, ttl, "1")
                if callable(getattr(rv, "__await__", None)):
                    await rv
                return
            rv = self.nonce_store.set(key, "1")
            if callable(getattr(rv, "__await__", None)):
                await rv
            return
        self._nonce_cache[key] = time.time() + max(1, int(ttl))
        # prosta pamięć w RAM, bez TTL cleanup (czyszczenie przy sprawdzaniu)
