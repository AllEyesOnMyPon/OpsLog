import time

from fastapi import Request
from fastapi.responses import JSONResponse


class _Bucket:
    __slots__ = ("capacity", "refill_per_sec", "tokens", "ts")

    def __init__(self, capacity: int, refill_per_sec: int):
        self.capacity = max(1, int(capacity))
        self.refill_per_sec = max(1, int(refill_per_sec))
        self.tokens = float(self.capacity)
        self.ts = time.monotonic()

    def allow(self) -> bool:
        now = time.monotonic()
        delta = max(0.0, now - self.ts)
        self.ts = now
        self.tokens = min(self.capacity, self.tokens + delta * self.refill_per_sec)
        if self.tokens >= 1.0:
            self.tokens -= 1.0
            return True
        return False


class TokenBucketRL:
    """
    Prosty token bucket per-emitter (in-memory) lub Redis jeśli podany.
    Konstruktor (ważne nazwy!):
      - default_capacity: int
      - default_refill:   int
      - per_emitter: Dict[str, Dict[str, int]]
      - redis: opcjonalny klient redis-py (async)
    """

    def __init__(
        self,
        app,
        *,
        default_capacity: int = 100,
        default_refill: int = 50,
        per_emitter: dict[str, dict[str, int]] | None = None,
        redis=None,
    ):
        self.app = app
        self.default_capacity = int(default_capacity)
        self.default_refill = int(default_refill)
        self.per_emitter = per_emitter or {}
        self.redis = redis
        self._mem: dict[str, _Bucket] = {}

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        request = Request(scope, receive=receive)
        path = request.url.path
        # bypassy dla sond/metryk
        if path in ("/metrics", "/health", "/healthz"):
            return await self.app(scope, receive, send)

        # z nagłówka, z request.state (HMAC), albo "unknown"
        emitter = (
            getattr(request.state, "emitter", None)
            or (request.headers.get("x-emitter") or "").strip()
            or "unknown"
        )

        # parametry kubełka dla emitera
        cfg = self.per_emitter.get(emitter, {})
        cap = int(cfg.get("capacity", self.default_capacity))
        ref = int(cfg.get("refill_per_sec", self.default_refill))

        # klucz limitu
        key = f"rl:emitter:{emitter}:{cap}:{ref}"

        allowed = True
        # Redisowa wersja (prosta: GET+SETEX i lokalna arytmetyka — OK na testy/dev)
        if self.redis:
            # używamy 1-tokenowego okna w 1/ref sec jako uproszczenie
            ttl = max(1, 1)
            try:
                v = await self.redis.get(key)  # bytes or None
                tokens = float(v.decode()) if v else float(cap)
                # bardzo uproszczony refill (co żądanie), wystarczający na sanity dev
                tokens = min(cap, tokens + ref * 0.1)  # 0.1s tick
                if tokens >= 1.0:
                    tokens -= 1.0
                    allowed = True
                else:
                    allowed = False
                await self.redis.setex(key, ttl, str(tokens))
            except Exception:
                # w razie problemów z redisem — nie dławić ruchu
                allowed = True
        else:
            b = self._mem.get(key)
            if not b:
                b = self._mem.setdefault(key, _Bucket(cap, ref))
            allowed = b.allow()

        # nagłówki informacyjne
        headers = {
            "X-RateLimit-Limit": str(cap),
            # heurystyka ile zostało (tylko in-memory daje sensowną liczbę)
            "X-RateLimit-Remaining": "1" if allowed else "0",
        }

        if not allowed:
            resp = JSONResponse(
                {"error": "rate limit exceeded", "emitter": emitter},
                status_code=429,
                headers=headers,
            )
            return await resp(scope, receive, send)

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                raw = list(message.get("headers") or [])
                for k, v in headers.items():
                    raw.append((k.encode("latin-1"), v.encode("latin-1")))
                message["headers"] = raw
            await send(message)

        return await self.app(scope, receive, send_with_headers)
