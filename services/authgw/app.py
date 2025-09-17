# services/authgw/app.py
from __future__ import annotations

import logging
import os
import time
from typing import Any

import yaml
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

from .downstream import Breaker, post_with_retry
from .hmac_mw import HmacAuthMiddleware
from .ratelimit_mw import TokenBucketRL

# Redis (optional)
try:
    from redis import asyncio as aioredis  # type: ignore
except Exception:  # pragma: no cover
    aioredis = None

logger = logging.getLogger("authgw.app")

app = FastAPI(title="LogOps Auth & RL Gateway")

# --- config ---
CFG_PATH = os.getenv("AUTHGW_CONFIG", os.path.join(os.path.dirname(__file__), "config.yaml"))
with open(CFG_PATH, encoding="utf-8") as fh:
    CFG: dict[str, Any] = yaml.safe_load(fh) or {}

# --- optional Redis ---
REDIS = None
storage_cfg = CFG.get("storage") or {}
redis_url = storage_cfg.get("redis_url")
if redis_url and aioredis:
    try:
        REDIS = aioredis.from_url(redis_url)
    except Exception:
        logger.warning("Redis init failed, continuing without Redis", exc_info=True)
        REDIS = None

# --- sections ---
auth_cfg = CFG.get("auth") or {}
auth_mode = (auth_cfg.get("mode", "any")).lower()
hmac_cfg = auth_cfg.get("hmac") or {}
clock_skew_s = int(hmac_cfg.get("clock_skew_sec", 30))
require_nonce = bool(hmac_cfg.get("require_nonce", True))

clients = {k: v for k, v in ((CFG.get("secrets") or {}).get("clients") or {}).items()}

ratelimit_cfg = CFG.get("ratelimit") or {}
rl_default_cap = int((ratelimit_cfg.get("per_emitter") or {}).get("capacity", 100))
rl_default_ref = int((ratelimit_cfg.get("per_emitter") or {}).get("refill_per_sec", 50))
rl_by_emitter: dict[str, dict[str, int]] = {}

forward_cfg = CFG.get("forward") or {}
FORWARD_URL = forward_cfg.get("url")  # e.g. "http://127.0.0.1:8080/v1/logs"
timeout_sec = int(forward_cfg.get("timeout_sec", 5))
timeouts = {"connect_ms": 2000, "read_ms": timeout_sec * 1000}

# retries / breaker
retries_cfg = CFG.get("retries") or {}
MAX_ATTEMPTS = int(retries_cfg.get("max_attempts", 3))
BASE_DELAY_MS = int(retries_cfg.get("base_delay_ms", 100))
MAX_DELAY_MS = int(retries_cfg.get("max_delay_ms", 1500))

breaker_cfg = CFG.get("breaker") or {}
_ft = breaker_cfg.get("failure_threshold", 0.2)
# przyjmij procent (np. 20) albo ułamek (0.2)
if isinstance(_ft, int | float) and _ft > 1:
    failure_threshold = float(_ft) / 100.0
else:
    failure_threshold = float(_ft) if isinstance(_ft, int | float) else 0.2
BREAKER = Breaker(
    failure_threshold=failure_threshold,
    window_sec=int(breaker_cfg.get("window_sec", 30)),
    half_open_after_sec=int(breaker_cfg.get("half_open_after_sec", 20)),
)

# backpressure
bp_cfg = CFG.get("backpressure") or {}
BP_ENABLED = bool(bp_cfg.get("enabled", True))
BP_MAX_BODY = int(bp_cfg.get("max_body_bytes", 200_000))

# ─── METRYKI ─────────────────────────────────────────────────────────────────
REJECTED = Counter(
    "logops_rejected_total",
    "AuthGW rejected requests.",
    ["reason", "emitter"],
)

AUTH_REQ = Counter(
    "auth_requests_total",
    "AuthGW requests by status and emitter",
    labelnames=("status", "emitter", "scenario_id"),
)
AUTH_LAT = Histogram(
    "auth_request_latency_seconds",
    "AuthGW request latency seconds",
    labelnames=("emitter", "scenario_id"),
    buckets=(0.005, 0.02, 0.05, 0.1, 0.25, 0.5, 1, 2),
)

# prewarm
DEFAULT_REASONS = [
    "unauthorized",
    "rate_limited",
    "too_large",
    "too_large_hdr",
    "bad_request",
    "bad_content_type",
    "forbidden",
    "clock_skew",
    "bad_signature",
    "bad_nonce",
    "unknown_client",
]


@app.on_event("startup")
def _prewarm_metrics():
    for r in DEFAULT_REASONS:
        REJECTED.labels(reason=r, emitter="unknown").inc(0)


logger.info(
    "AuthGW config: mode=%s skew=%ss require_nonce=%s forward_url=%s",
    auth_mode,
    clock_skew_s,
    require_nonce,
    FORWARD_URL,
)

# --- middlewares (HMAC / RL) ---
app.add_middleware(
    HmacAuthMiddleware,
    mode=auth_mode,
    clients=clients,
    nonce_store=REDIS,
    clock_skew_sec=clock_skew_s,
    require_nonce=require_nonce,
)

app.add_middleware(
    TokenBucketRL,
    default_capacity=rl_default_cap,
    default_refill=rl_default_ref,
    per_emitter=rl_by_emitter,
    redis=REDIS,
)


# --- helpers ---
def _labels_from_headers(req: Request) -> tuple[str, str]:
    emitter = (req.headers.get("x-emitter") or "").strip()
    scenario_id = (req.headers.get("x-scenario-id") or "").strip() or (
        req.headers.get("x-scenario") or ""
    ).strip()
    if not emitter:
        emitter = getattr(req.state, "emitter", None) or "unknown"
    if not scenario_id:
        scenario_id = getattr(req.state, "scenario_id", None) or "na"
    return emitter, scenario_id


def _safe_format(s: str, ctx: dict[str, Any]) -> str:
    class _Safe(dict):
        def __missing__(self, k):  # leave {k} as-is
            return "{" + k + "}"

    try:
        return str(s).format_map(_Safe(ctx))
    except Exception:
        return str(s)


def _build_forward_headers(
    req: Request, emitter: str, scenario_id: str, content_type: str
) -> dict[str, str]:
    headers_cfg = forward_cfg.get("headers") or {}

    client_ip = getattr(req.state, "client_ip", None) or (req.client.host if req.client else "")
    ctx = {
        "client_ip": client_ip,
        "emitter": emitter,
        "scenario_id": scenario_id,
        "api_key": getattr(req.state, "api_key", ""),
        "method": req.method,
        "path": req.url.path,
        "content_type": content_type,
    }
    out = {k: _safe_format(v, ctx) for k, v in headers_cfg.items()}
    out.setdefault("Content-Type", content_type)
    out.setdefault("X-Emitter", emitter)
    out.setdefault("X-Scenario-Id", scenario_id)
    return out


def _infer_reason(status_code: int, detail: Any) -> str:
    text = (str(detail) if detail is not None else "").lower()
    if status_code == 429:
        return "rate_limited"
    if status_code == 401:
        if "signature" in text:
            return "bad_signature"
        if "nonce" in text or "replay" in text:
            return "bad_nonce"
        if "timestamp" in text or "skew" in text:
            return "clock_skew"
        if "api key" in text or "client" in text:
            return "unknown_client"
        return "unauthorized"
    if status_code == 415:
        return "bad_content_type"
    if status_code == 413:
        return "too_large"
    if status_code == 400:
        if "json" in text or "body" in text:
            return "bad_json"
        return "bad_request"
    if status_code == 403:
        return "forbidden"
    return f"http_{status_code}"


# --- globalny handler HTTPException (np. z HMAC/RL) ---
@app.exception_handler(HTTPException)
async def _http_exc_handler(request: Request, exc: HTTPException):
    emitter, scenario_id = _labels_from_headers(request)
    reason = _infer_reason(exc.status_code, exc.detail)
    REJECTED.labels(reason=reason, emitter=emitter).inc()
    return JSONResponse(
        {"detail": exc.detail},
        status_code=exc.status_code,
        headers={"X-AuthGW-Reason": reason, "X-AuthGW-Counted": "1"},
    )


# --- middleware: latency + liczenie odrzuceń ---
@app.middleware("http")
async def _observe_and_count_mw(request: Request, call_next):
    start_t = time.monotonic()
    emitter, scenario_id = _labels_from_headers(request)

    try:
        response = await call_next(request)
    except HTTPException:
        raise
    except Exception:
        resp = JSONResponse({"error": "internal_error"}, status_code=500)
        AUTH_REQ.labels("500", emitter, scenario_id).inc()
        AUTH_LAT.labels(emitter, scenario_id).observe(max(0.0, time.monotonic() - start_t))
        return resp

    AUTH_REQ.labels(str(response.status_code), emitter, scenario_id).inc()
    AUTH_LAT.labels(emitter, scenario_id).observe(max(0.0, time.monotonic() - start_t))

    if request.url.path == "/ingest" and 400 <= response.status_code < 500:
        if response.headers.get("X-AuthGW-Counted") != "1":
            reason = (
                response.headers.get("X-Backpressure-Reason")
                or response.headers.get("X-AuthGW-Reason")
                or _infer_reason(response.status_code, None)
            )
            REJECTED.labels(reason=reason, emitter=emitter).inc()
            response.headers["X-AuthGW-Counted"] = "1"
            response.headers.setdefault("X-AuthGW-Reason", reason)

    return response


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


@app.get("/health")
async def health():
    return await healthz()


@app.post("/ingest")
async def ingest(request: Request):
    """
    Passthrough dowolnego Content-Type do IngestGW z zachowaniem nagłówków transportowych.
    HMAC oraz rate-limiting obsługują middleware’y.
    """
    try:
        raw = await request.body()
    except Exception:
        return JSONResponse({"error": "cannot read request body"}, 400)

    actual_len = len(raw)
    content_length_hdr = request.headers.get("content-length")
    content_type = (request.headers.get("content-type") or "application/json").split(";")[0].lower()

    if BP_ENABLED:
        try:
            if content_length_hdr and int(content_length_hdr) > BP_MAX_BODY:
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
            pass

        if actual_len > BP_MAX_BODY:
            return JSONResponse(
                {
                    "error": "payload too large",
                    "max_body_bytes": BP_MAX_BODY,
                    "actual_bytes": actual_len,
                },
                status_code=413,
                headers={"X-Backpressure-Reason": "too_large"},
            )

    if not FORWARD_URL:
        return JSONResponse({"error": "forward url not configured"}, 500)

    emitter, scenario_id = _labels_from_headers(request)
    fwd_headers = _build_forward_headers(request, emitter, scenario_id, content_type)

    try:
        resp = await post_with_retry(
            FORWARD_URL,
            content=raw,  # passthrough bytes — bez ingerencji w body
            timeout_ms=(timeouts.get("connect_ms", 2000), timeouts.get("read_ms", 5000)),
            attempts=MAX_ATTEMPTS,
            base_delay_ms=BASE_DELAY_MS,
            max_delay_ms=MAX_DELAY_MS,
            breaker=BREAKER,
            headers=fwd_headers,
        )
    except RuntimeError as e:
        msg = str(e)
        if "circuit_open" in msg:
            return JSONResponse({"error": "circuit_open"}, status_code=503)
        return JSONResponse({"error": msg}, status_code=502)
    except Exception as e:  # awaryjnie
        return JSONResponse({"error": f"downstream_error: {e!r}"}, status_code=502)

    return Response(
        content=resp.content,
        status_code=resp.status_code,
        media_type=resp.headers.get("content-type", "application/json"),
    )


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
