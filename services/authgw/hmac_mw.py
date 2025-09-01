import os
import base64
import hashlib
import hmac
import time
import logging
from datetime import datetime
from typing import Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

# Ścieżki bez autoryzacji (health/metrics)
ALLOW_PATHS = {"/healthz", "/metrics"}

logger = logging.getLogger("authgw.hmac")


def _parse_iso8601(ts: str) -> int:
    """Zwraca timestamp (sekundy) z ISO8601, akceptuje sufiks 'Z'."""
    if ts.endswith("Z"):
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    else:
        dt = datetime.fromisoformat(ts)
    return int(dt.timestamp())


def _path_with_query(request) -> str:
    """Zwróć ścieżkę z zapytaniem (bez schematu/hosta)."""
    path = request.url.path
    return path + (f"?{request.url.query}" if request.url.query else "")


class HmacAuthMiddleware(BaseHTTPMiddleware):
    """
    Tryby:
      - "off"     : brak auth
      - "apikey"  : wymaga X-Api-Key
      - "hmac"    : wymaga HMAC (X-Api-Key, X-Timestamp, X-Content-SHA256, X-Signature [+ X-Nonce opcjonalnie])
      - "any"     : akceptuje apikey albo pełny HMAC

    client_db: { <api_key>: { "secret": "...", "emitter": "..." } }
    """

    def __init__(
        self,
        app,
        mode: str,
        client_db: dict,
        redis=None,
        clock_skew: float = 300,
        require_nonce: bool = True,
    ):
        super().__init__(app)
        self.mode = (mode or "hmac").lower()
        self.client_db = client_db or {}
        self.redis = redis
        self.clock_skew = float(clock_skew)
        self.require_nonce = bool(require_nonce)
        # Debug tylko, gdy explicit ENV
        self.env_debug = str(os.getenv("AUTHGW_DEBUG", "0")).lower() in {"1", "true", "yes", "on"}

    async def dispatch(self, request, call_next):
        # Bez auth dla health/metrics lub gdy tryb "off"
        if request.url.path in ALLOW_PATHS or self.mode == "off":
            return await call_next(request)

        api_key: Optional[str] = request.headers.get("X-Api-Key")
        if not api_key:
            return JSONResponse({"error": "missing X-Api-Key"}, 401)

        client = self.client_db.get(api_key)
        if not client:
            return JSONResponse({"error": "invalid api key"}, 401)

        # tryb api_key → przekaż emitter downstream
        if self.mode == "apikey":
            scope_headers = list(request.headers.raw)
            scope_headers.append((b"x-emitter", client["emitter"].encode()))
            request.scope["headers"] = scope_headers
            return await call_next(request)

        # Tryby HMAC/ANY
        ts = request.headers.get("X-Timestamp")
        sign = request.headers.get("X-Signature")
        body_hash_hdr = request.headers.get("X-Content-SHA256")
        nonce = request.headers.get("X-Nonce")

        # W "any" brak kompletów HMAC → traktuj jak apikey
        if self.mode == "any" and not (ts and sign and body_hash_hdr):
            scope_headers = list(request.headers.raw)
            scope_headers.append((b"x-emitter", client["emitter"].encode()))
            request.scope["headers"] = scope_headers
            return await call_next(request)

        # Wymagamy kompletu HMAC
        if not (ts and sign and body_hash_hdr):
            return JSONResponse({"error": "missing hmac headers"}, 401)

        # Parsowanie TS
        try:
            t_client = _parse_iso8601(ts)
        except Exception:
            return JSONResponse({"error": "bad X-Timestamp"}, 400)

        # Skew check
        now = time.time()
        diff = abs(now - float(t_client))

        # Debug tylko, gdy env włączony + nagłówek proszący o debug
        if self.env_debug and request.headers.get("X-Debug-HMAC") == "1":
            logger.debug(
                "HMAC debug: now=%.3f client=%.3f diff=%.3f skew=%.3f mode=%s",
                now, float(t_client), diff, self.clock_skew, self.mode
            )

        if diff > self.clock_skew:
            return JSONResponse({"error": "timestamp skew"}, 401)

        # Nonce / anty-replay
        if self.require_nonce:
            if not nonce:
                return JSONResponse({"error": "missing X-Nonce"}, 401)
            if self.redis:
                key = f"hmac:nonce:{api_key}:{nonce}"
                added = await self.redis.setnx(key, "1")
                if not added:
                    return JSONResponse({"error": "replay detected"}, 401)
                await self.redis.expire(key, 300)

        # Hash ciała
        raw = await request.body()
        calc_hash = hashlib.sha256(raw).hexdigest()
        if body_hash_hdr and body_hash_hdr != calc_hash:
            return JSONResponse({"error": "body hash mismatch"}, 401)

        # Kanoniczny ciąg i podpis
        canonical = "\n".join([
            request.method.upper(),
            _path_with_query(request),
            ts,
            calc_hash,
        ]).encode()

        mac = hmac.new(client["secret"].encode(), canonical, hashlib.sha256).digest()
        expected = base64.b64encode(mac).decode()
        if not hmac.compare_digest(sign, expected):
            return JSONResponse({"error": "bad signature"}, 401)

        # Dołóż emitter downstream (np. do RL)
        scope_headers = list(request.headers.raw)
        scope_headers.append((b"x-emitter", client["emitter"].encode()))
        request.scope["headers"] = scope_headers

        return await call_next(request)
