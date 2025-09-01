# services/authgw/app.py
from __future__ import annotations

import os
import json
import logging
from typing import Any, Dict

import yaml
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from prometheus_client import Counter, generate_latest, CONTENT_TYPE_LATEST

# importy RELATYWNE (do pakietu services.authgw)
from .hmac_mw import HmacAuthMiddleware
from .ratelimit_mw import TokenBucketRL
from .downstream import Breaker, post_with_retry

# Redis opcjonalnie
try:
    from redis import asyncio as aioredis  # type: ignore
except Exception:  # pragma: no cover
    aioredis = None  # brak redis → nonce weryfikacja tylko nagłówkiem

logger = logging.getLogger("authgw.app")

app = FastAPI(title="LogOps Auth & RL Gateway")

# --- config ---
CFG_PATH = os.getenv(
    "AUTHGW_CONFIG",
    os.path.join(os.path.dirname(__file__), "config.yaml"),
)
with open(CFG_PATH, "r", encoding="utf-8") as fh:
    CFG: Dict[str, Any] = yaml.safe_load(fh) or {}

# --- opcjonalny Redis ---
REDIS = None
storage_cfg = (CFG.get("storage") or {})
redis_url = storage_cfg.get("redis_url")
if redis_url and aioredis:
    try:
        REDIS = aioredis.from_url(redis_url)
    except Exception:  # pragma: no cover
        logger.warning("Redis init failed, continuing without Redis", exc_info=True)
        REDIS = None

# --- sekcje konfiguracyjne (dopasowane do YAML) ---
auth_cfg = (CFG.get("auth") or {})
auth_mode = (auth_cfg.get("mode", "any")).lower()  # "none"/"api_key"/"hmac"/"any"
hmac_cfg = (auth_cfg.get("hmac") or {})
clock_skew_s = int(hmac_cfg.get("clock_skew_sec", 30))
require_nonce = bool(hmac_cfg.get("require_nonce", True))

clients = {
    k: v for k, v in ((CFG.get("secrets") or {}).get("clients") or {}).items()
}

ratelimit_cfg = (CFG.get("ratelimit") or {})
rl_default_cap = int(((ratelimit_cfg.get("per_emitter") or {}).get("capacity", 100)))
rl_default_ref = int(
    ((ratelimit_cfg.get("per_emitter") or {}).get("refill_per_sec", 50))
)
rl_by_emitter: Dict[str, Dict[str, int]] = {}  # na przyszłość: per-emitter override

forward_cfg = (CFG.get("forward") or {})
FORWARD_URL = forward_cfg.get("url")  # np. "http://127.0.0.1:8080/v1/logs"
timeout_sec = int(forward_cfg.get("timeout_sec", 5))
# mapa na ms dla httpx.Timeout:
timeouts = {"connect_ms": 2000, "read_ms": timeout_sec * 1000}

# retry i breaker – bezpieczne domyślne, jeśli brak w YAML
retries = CFG.get("retries") or {
    "max_attempts": 3,
    "base_delay_ms": 100,
    "max_delay_ms": 1500,
}
brk_cfg = CFG.get("breaker") or {
    "failure_threshold": 20,
    "window_sec": 30,
    "half_open_after_sec": 20,
}

# --- backpressure ---
bp_cfg = (CFG.get("backpressure") or {})
BP_ENABLED = bool(bp_cfg.get("enabled", True))
BP_MAX_BODY = int(bp_cfg.get("max_body_bytes", 200_000))
BP_MAX_ITEMS = int(bp_cfg.get("max_items", 1000))

REJECTED = Counter(
    "logops_rejected_total",
    "AuthGW rejected requests due to backpressure.",
    ["reason", "emitter"],
)

BREAKER = Breaker(
    failure_threshold=(int(brk_cfg.get("failure_threshold", 20)) / 100.0),  # procent → ułamek
    window_sec=int(brk_cfg.get("window_sec", 30)),
    half_open_after_sec=int(brk_cfg.get("half_open_after_sec", 20)),
)

logger.info(
    "AuthGW config: mode=%s skew=%s require_nonce=%s forward_url=%s",
    auth_mode,
    clock_skew_s,
    require_nonce,
    FORWARD_URL,
)

# --- middlewares ---
app.add_middleware(
    HmacAuthMiddleware,
    mode=auth_mode,
    client_db=clients,
    redis=REDIS,
    clock_skew=clock_skew_s,
    require_nonce=require_nonce,
)

app.add_middleware(
    TokenBucketRL,
    default_capacity=rl_default_cap,
    default_refill=rl_default_ref,
    per_emitter=rl_by_emitter,
    redis=REDIS,
)


# --- routes ---
@app.get("/healthz")
async def healthz():
    ok = True
    if REDIS:
        try:
            await REDIS.ping()
        except Exception:
            ok = False
    return {"ok": ok}


@app.post("/ingest")
async def ingest(request: Request):
    # 1) raw body + długość (na potrzeby backpressure/telemetrii)
    raw = await request.body()
    actual_len = len(raw)
    content_length_hdr = request.headers.get("content-length")
    emitter = request.headers.get("x-emitter", "unknown")  # z HMAC MW
    client_ip = request.client.host if request.client else "unknown"
    ua = request.headers.get("user-agent", "-")

    logger.info(
        "ingest_req ip=%s emitter=%s len=%s ua=%s",
        client_ip,
        emitter,
        actual_len,
        ua,
    )

    # 2) backpressure: bytes (nagłówek + rzeczywisty odczyt)
    if BP_ENABLED:
        try:
            if content_length_hdr and int(content_length_hdr) > BP_MAX_BODY:
                REJECTED.labels(reason="too_large_hdr", emitter=emitter).inc()
                return JSONResponse(
                    {
                        "error": "payload too large",
                        "max_body_bytes": BP_MAX_BODY,
                        "content_length_hdr": int(content_length_hdr),
                    },
                    status_code=413,
                    headers={"X-Backpressure-Reason": "too_large_hdr"},
                )
        except Exception:
            # jeżeli nagłówek był nie-liczbowy, po prostu sprawdź rzeczywistą długość
            pass

        if actual_len > BP_MAX_BODY:
            REJECTED.labels(reason="too_large", emitter=emitter).inc()
            return JSONResponse(
                {
                    "error": "payload too large",
                    "max_body_bytes": BP_MAX_BODY,
                    "actual_bytes": actual_len,
                },
                status_code=413,
                headers={"X-Backpressure-Reason": "too_large"},
            )

    # 3) parse JSON
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception:
        return JSONResponse({"error": "bad json"}, 400)

    # 4) backpressure: items (jeśli lista)
    if BP_ENABLED and isinstance(payload, list):
        items = len(payload)
        if items > BP_MAX_ITEMS:
            REJECTED.labels(reason="too_many_items", emitter=emitter).inc()
            return JSONResponse(
                {
                    "error": "too many items",
                    "max_items": BP_MAX_ITEMS,
                    "actual_items": items,
                },
                status_code=413,
                headers={"X-Backpressure-Reason": "too_many_items"},
            )

    if not FORWARD_URL:
        return JSONResponse({"error": "forward url not configured"}, 500)

    # 5) forward do Ingest Gateway (z retry + breaker)
    try:
        r = await post_with_retry(
            FORWARD_URL,
            json_payload=payload,
            timeout_ms=(timeouts.get("connect_ms", 2000), timeouts.get("read_ms", 5000)),
            attempts=retries.get("max_attempts", 3),
            base_delay_ms=retries.get("base_delay_ms", 100),
            max_delay_ms=retries.get("max_delay_ms", 1500),
            breaker=BREAKER,
        )
        try:
            content = r.json()
        except Exception:
            content = {"downstream_text": r.text}
        return JSONResponse(content, status_code=r.status_code)
    except RuntimeError as e:
        code = 503 if "circuit_open" in str(e) else 502
        return JSONResponse({"error": str(e)}, code)


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
