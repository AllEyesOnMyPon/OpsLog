# services/core/app.py
from __future__ import annotations

import json
import logging
import os
import time
from collections import Counter, deque
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter as PcCounter,
    Gauge,
    Histogram,
    generate_latest,
)

logger = logging.getLogger("core.app")

app = FastAPI(title="LogOps Core")


def _env_bool(name: str, default: bool) -> bool:
    v = os.getenv(name, "")
    if v == "":
        return default
    return v.lower() not in ("0", "false", "no", "off")


# --- S13: brak twardych ścieżek, domyślne tylko jako fallback ---
CORE_MAX_BODY_BYTES = int(os.getenv("CORE_MAX_BODY_BYTES", "1048576"))
CORE_MAX_ITEMS = int(os.getenv("CORE_MAX_ITEMS", "5000"))
CORE_SINK_FILE = _env_bool("CORE_SINK_FILE", False)

# Priorytet: LOGOPS_SINK_DIR (S13) -> CORE_SINK_DIR -> ./data/ingest
CORE_SINK_DIR = os.getenv("LOGOPS_SINK_DIR", os.getenv("CORE_SINK_DIR", "./data/ingest"))

CORE_DEBUG_SAMPLE = _env_bool("CORE_DEBUG_SAMPLE", False)
CORE_DEBUG_SAMPLE_SIZE = int(os.getenv("CORE_DEBUG_SAMPLE_SIZE", "10"))
CORE_RING_SIZE = int(os.getenv("CORE_RING_SIZE", "200"))

_RING = deque(maxlen=max(1, CORE_RING_SIZE))

CORE_INFLIGHT = Gauge("core_inflight", "Number of in-flight core requests.")

CORE_REQ_LAT = Histogram(
    "core_request_latency_seconds",
    "Core request latency seconds",
    labelnames=("emitter", "scenario_id"),
    buckets=(0.005, 0.02, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, float("inf")),
)

CORE_ACCEPTED = PcCounter(
    "core_accepted_total",
    "Total accepted records.",
    labelnames=("emitter", "scenario_id"),
)

CORE_LEVEL_TOTAL = PcCounter(
    "core_level_total",
    "Records by level.",
    labelnames=("level",),
)

CORE_BYTES = PcCounter(
    "core_bytes_total",
    "Total request body bytes received.",
)

CORE_REJECTED = PcCounter(
    "core_rejected_total",
    "Core rejected requests (backpressure).",
    labelnames=("reason",),
)


def _labels_from_headers(req: Request) -> tuple[str, str]:
    emitter = (req.headers.get("x-emitter") or "").strip() or "unknown"
    scenario_id = (
        (req.headers.get("x-scenario-id") or "").strip()
        or (req.headers.get("x-scenario") or "").strip()
        or "na"
    )
    return emitter, scenario_id


def _ensure_core_labels(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for r in records:
        if not isinstance(r, dict):
            continue
        r.setdefault("app", "logops")
        r.setdefault("source", "core")
        out.append(r)
    return out


def _parse_payload(raw: bytes) -> list[dict[str, Any]]:
    try:
        payload: Any = json.loads(raw.decode("utf-8"))
    except Exception as err:
        raise HTTPException(status_code=400, detail="bad json") from err

    if isinstance(payload, list):
        items = []
        bad = 0
        for itm in payload:
            if isinstance(itm, dict):
                items.append(itm)
            else:
                bad += 1
        if bad and not items:
            raise HTTPException(status_code=422, detail="invalid items in array")
        return items

    if isinstance(payload, dict):
        return [payload]

    raise HTTPException(status_code=400, detail="bad json")


def _write_ndjson(records: list[dict[str, Any]], *, emitter: str, scenario_id: str) -> None:
    if not (CORE_SINK_FILE and records):
        return
    try:
        os.makedirs(CORE_SINK_DIR, exist_ok=True)
        day = datetime.now(UTC).strftime("%Y%m%d")
        path = os.path.join(CORE_SINK_DIR, f"{day}.ndjson")
        with open(path, "a", encoding="utf-8") as fh:
            for item in records:
                row = dict(item)
                row.setdefault("app", "logops")
                row.setdefault("source", "core")
                row.setdefault("emitter", emitter or "unknown")
                row.setdefault("scenario_id", scenario_id or "na")
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:
        logger.exception("core sink write failed")


def _observe(emitter: str, scenario_id: str, start_t: float) -> None:
    try:
        CORE_REQ_LAT.labels(emitter, scenario_id).observe(max(0.0, time.perf_counter() - start_t))
    except Exception:
        pass


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/_debug/hdrs")
async def debug_hdrs(request: Request):
    emitter, scenario_id = _labels_from_headers(request)
    return {
        "headers": dict(request.headers),
        "chosen": {"emitter": emitter, "scenario_id": scenario_id},
        "config": {
            "CORE_MAX_BODY_BYTES": CORE_MAX_BODY_BYTES,
            "CORE_MAX_ITEMS": CORE_MAX_ITEMS,
            "CORE_SINK_FILE": CORE_SINK_FILE,
            "CORE_SINK_DIR": CORE_SINK_DIR,
            "CORE_RING_SIZE": CORE_RING_SIZE,
        },
    }


@app.get("/_debug/stats")
def debug_stats():
    sample = list(_RING)[-min(len(_RING), CORE_DEBUG_SAMPLE_SIZE) :]
    for s in sample:
        msg = s.get("msg")
        if isinstance(msg, str) and len(msg) > 200:
            s["msg"] = msg[:200] + "…"
    return {"ring_len": len(_RING), "sample": sample}


@app.post("/v1/logs")
async def v1_logs(request: Request):
    try:
        CORE_INFLIGHT.inc()
    except Exception:
        pass

    start_t = time.perf_counter()
    emitter, scenario_id = _labels_from_headers(request)

    try:
        raw = await request.body()
    except Exception as err:
        _observe(emitter, scenario_id, start_t)
        raise HTTPException(status_code=400, detail="cannot read body") from err

    try:
        CORE_BYTES.inc(len(raw))
    except Exception:
        pass

    if len(raw) > CORE_MAX_BODY_BYTES:
        CORE_REJECTED.labels("too_large").inc()
        _observe(emitter, scenario_id, start_t)
        raise HTTPException(status_code=413, detail="payload too large")

    records = _parse_payload(raw)

    if len(records) > CORE_MAX_ITEMS:
        CORE_REJECTED.labels("too_many_items").inc()
        _observe(emitter, scenario_id, start_t)
        raise HTTPException(status_code=413, detail="too many items")

    records = _ensure_core_labels(records)

    lvl_counts = Counter()
    for r in records:
        lvl = r.get("level") or "INFO"
        if isinstance(lvl, str):
            lvl_counts[lvl.upper().strip()] += 1

    for lvl, cnt in lvl_counts.items():
        try:
            CORE_LEVEL_TOTAL.labels(lvl).inc(cnt)
        except Exception:
            pass

    _write_ndjson(records, emitter=emitter, scenario_id=scenario_id)

    try:
        for r in records:
            _RING.append({k: v for k, v in r.items() if not k.startswith("_")})
    except Exception:
        pass

    try:
        if records:
            CORE_ACCEPTED.labels(emitter, scenario_id).inc(len(records))
    except Exception:
        pass

    _observe(emitter, scenario_id, start_t)
    try:
        CORE_INFLIGHT.dec()
    except Exception:
        pass

    return {"accepted": len(records)}
