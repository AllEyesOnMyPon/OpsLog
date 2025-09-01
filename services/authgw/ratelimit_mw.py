# services/authgw/ratelimit_mw.py
from __future__ import annotations

import math
import time
from typing import Dict, Optional, Tuple

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

# Ścieżki wyłączone z limitowania (health / metryki)
ALLOW_PATHS = {"/healthz", "/metrics"}


class TokenBucketRL(BaseHTTPMiddleware):
    """
    Prosty token-bucket per-emitter (w Redis lub lokalnie).
    - Każdy request zużywa 1 token.
    - Tokeny uzupełniają się w tempie `refill_per_sec` aż do `capacity`.
    - Gdy brak tokenów, 429 + Retry-After (czas do odnowienia 1 tokena).
    """

    def __init__(
        self,
        app,
        default_capacity: float,
        default_refill: float,
        per_emitter: Optional[Dict[str, Dict[str, float]]] = None,
        redis=None,  # `redis.asyncio` lub None
    ):
        super().__init__(app)
        self.default_capacity = float(default_capacity)
        self.default_refill = float(default_refill)
        self.per_emitter = per_emitter or {}
        self.redis = redis
        # fallback in-memory: emitter -> (tokens, last_ts)
        self.local: Dict[str, Tuple[float, float]] = {}

    # ---------- wspólne narzędzia ----------

    @staticmethod
    def _calc_next(tokens: float, last: float, now: float, capacity: float, refill: float) -> float:
        """Uzupełnij tokeny upływem czasu (clamp do capacity)."""
        if refill <= 0:
            # brak uzupełniania → tylko spadek
            return min(tokens, capacity)
        replenished = tokens + (now - last) * refill
        return min(replenished, capacity)

    @staticmethod
    def _retry_after(tokens: float, capacity: float, refill: float) -> int:
        """Sekundy do uzyskania 1 tokena (co najmniej 1s)."""
        if refill <= 0:
            return 1
        needed = max(0.0, 1.0 - tokens)  # ile brakuje do 1
        seconds = needed / refill
        return max(1, int(math.ceil(seconds)))

    # ---------- ścieżka Redis ----------

    async def _redis_take(self, emitter: str, capacity: float, refill: float):
        now = time.time()
        k_last = f"rl:{emitter}:last"
        k_tok = f"rl:{emitter}:tok"

        last_raw, tok_raw = await self.redis.mget(k_last, k_tok)
        last = float(last_raw) if last_raw else now
        tokens = float(tok_raw) if tok_raw else float(capacity)

        # uzupełnij
        tokens = self._calc_next(tokens, last, now, capacity, refill)

        if tokens < 1.0:
            # zapisz stan i odmów
            await self.redis.set(k_last, now, ex=3600)
            await self.redis.set(k_tok, tokens, ex=3600)
            return False, int(tokens), self._retry_after(tokens, capacity, refill)

        # zużyj 1 token i zapisz
        tokens -= 1.0
        await self.redis.set(k_last, now, ex=3600)
        await self.redis.set(k_tok, tokens, ex=3600)
        return True, int(tokens), 0

    # ---------- ścieżka lokalna ----------

    def _local_take(self, emitter: str, capacity: float, refill: float):
        now = time.time()
        tokens, last = self.local.get(emitter, (float(capacity), now))

        tokens = self._calc_next(tokens, last, now, capacity, refill)

        if tokens < 1.0:
            self.local[emitter] = (tokens, now)
            return False, int(tokens), self._retry_after(tokens, capacity, refill)

        tokens -= 1.0
        self.local[emitter] = (tokens, now)
        return True, int(tokens), 0

    # ---------- middleware ----------

    async def dispatch(self, request, call_next):
        # wyjątki z limitu
        if request.url.path in ALLOW_PATHS:
            return await call_next(request)

        emitter = (
            request.headers.get("x-emitter")
            or request.headers.get("X-Emitter")
            or "unknown"
        )

        cfg = self.per_emitter.get(emitter, {})
        capacity = float(cfg.get("capacity", self.default_capacity))
        refill = float(cfg.get("refill_per_sec", self.default_refill))

        if self.redis:
            ok, remaining, retry_after = await self._redis_take(emitter, capacity, refill)
        else:
            ok, remaining, retry_after = self._local_take(emitter, capacity, refill)

        # standardowe nagłówki ratelimit (proste)
        limit_headers = {
            "X-RateLimit-Limit": str(int(capacity)),
            "X-RateLimit-Remaining": str(max(0, remaining)),
        }

        if not ok:
            hdrs = dict(limit_headers)
            if retry_after > 0:
                hdrs["Retry-After"] = str(retry_after)
            return JSONResponse({"error": "rate limit exceeded"}, status_code=429, headers=hdrs)

        # przepuść dalej i dołóż nagłówki do odpowiedzi
        resp = await call_next(request)
        for k, v in limit_headers.items():
            resp.headers[k] = v
        return resp
