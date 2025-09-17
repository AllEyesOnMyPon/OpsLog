from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections import Counter
from datetime import UTC, datetime
from json import JSONDecodeError
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from .metrics import (
    ACCEPTED_TOTAL,
    BATCH_LATENCY,
    BATCH_SIZE,
    DEBUG_SAMPLE,
    DEBUG_SAMPLE_SIZE,
    INGESTED_TOTAL,
    METRIC_INFLIGHT,
    MISSING_LEVEL_TOTAL,
    MISSING_TS_TOTAL,
    PARSE_ERRORS,
    SINK_DIR_PATH,
    SINK_FILE,
)

# normalizacja pojedynczego rekordu
from .normalize import normalize_record
from .parsers import parse_csv_text_body, parse_syslog_line

logger = logging.getLogger("ingestgw.app")

app = FastAPI(title="LogOps Ingest Gateway")

# URL Core (forward); nadpisz envem CORE_URL
CORE_URL = os.getenv("CORE_URL", "http://127.0.0.1:8095/v1/logs")


def enforce_labels(
    records: list[dict[str, Any]],
    *,
    emitter: str,
    scenario_id: str,
    app: str = "logops",
    source: str = "ingest",
) -> list[dict[str, Any]]:
    """
    Nagłówek ma pierwszeństwo: nadpisujemy pola emitter/scenario_id.
    Doklejamy też app/source.
    """
    out: list[dict[str, Any]] = []
    for n in records:
        if not isinstance(n, dict):
            continue
        n["app"] = app
        n["source"] = source
        if emitter:
            n["emitter"] = emitter
        if scenario_id:
            n["scenario_id"] = scenario_id
        out.append(n)
    return out


# ── mały helper HTTP z retry (headers wspierane) ─────────────────────────────
async def _post_with_retry(
    url: str,
    *,
    json_payload: Any,
    headers: dict[str, str] | None = None,
    attempts: int = 3,
    base_delay_ms: int = 100,
    max_delay_ms: int = 1500,
    connect_s: float = 2.0,
    read_s: float = 5.0,
    write_s: float = 5.0,
    pool_s: float = 2.0,
) -> httpx.Response:
    delay = base_delay_ms / 1000.0
    max_delay = max_delay_ms / 1000.0
    last_exc: Exception | None = None

    timeout = httpx.Timeout(connect=connect_s, read=read_s, write=write_s, pool=pool_s)
    async with httpx.AsyncClient(timeout=timeout) as client:
        for attempt in range(1, max(1, attempts) + 1):
            try:
                return await client.post(url, json=json_payload, headers=headers)
            except Exception as e:
                last_exc = e
                if attempt >= attempts:
                    break
                await asyncio.sleep(delay)
                delay = min(delay * 2, max_delay)

    raise RuntimeError(
        f"downstream_error: {last_exc!r}" if last_exc else "downstream_error: unknown"
    )


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/v1/logs")
async def ingest_logs(request: Request):
    # metryka inflight
    try:
        METRIC_INFLIGHT.inc()  # type: ignore[name-defined]
    except Exception:
        pass

    t0 = time.perf_counter()
    try:
        content_type = (request.headers.get("content-type") or "").lower()
        emitter_name = (request.headers.get("x-emitter") or "").strip() or "unknown"
        # Obsługujemy obie formy scenariusza (wsteczna zgodność)
        scenario_id = (
            (request.headers.get("x-scenario-id") or "").strip()
            or (request.headers.get("x-scenario") or "").strip()
            or "na"
        )

        # 1) Body -> records
        if content_type.startswith("text/plain"):
            text = (await request.body()).decode("utf-8", errors="replace")
            records: list[dict[str, Any]] = [
                parse_syslog_line(ln) for ln in text.splitlines() if ln.strip()
            ]
        elif content_type.startswith("text/csv"):
            text = (await request.body()).decode("utf-8", errors="replace")
            records = parse_csv_text_body(text)
        else:
            try:
                payload: Any = await request.json()
            except JSONDecodeError:
                raise HTTPException(status_code=400, detail="Invalid JSON body") from None

            if isinstance(payload, list):
                records = payload
            elif isinstance(payload, dict):
                records = [payload]
            else:
                raise HTTPException(
                    status_code=400,
                    detail="Payload must be object or array of objects",
                )

            # prosta walidacja bez Pydantic
            invalid_idx: list[int] = []
            validated: list[dict[str, Any]] = []
            for i, item in enumerate(records):
                if isinstance(item, dict):
                    validated.append(item)
                else:
                    invalid_idx.append(i)

            if invalid_idx:
                try:
                    # DOKLEJ scenariusz do licznika błędów parsowania
                    PARSE_ERRORS.labels(emitter=emitter_name, scenario_id=scenario_id).inc(
                        len(invalid_idx)
                    )  # type: ignore[name-defined]
                except Exception:
                    pass
                if not validated:
                    raise HTTPException(
                        status_code=422,
                        detail={
                            "error": "Invalid records in JSON array",
                            "invalid_indices": invalid_idx[:50],
                            "count": len(invalid_idx),
                        },
                    )
            records = validated

        # 2) Normalizacja
        counters = Counter()
        sample: list[dict[str, Any]] = []
        normalized: list[dict[str, Any]] = []

        for rec in records:
            norm = normalize_record(rec if isinstance(rec, dict) else {})
            normalized.append(norm)
            if norm.get("_missing_ts"):
                counters["missing_ts"] += 1
            if norm.get("_missing_level"):
                counters["missing_level"] += 1
            try:
                if DEBUG_SAMPLE and len(sample) < DEBUG_SAMPLE_SIZE:  # type: ignore[name-defined]
                    sample.append({k: v for k, v in norm.items() if not k.startswith("_")})
            except Exception:
                pass

        # 3) Wymuszenie etykiet z nagłówków (nagłówek ma pierwszeństwo)
        normalized = enforce_labels(
            normalized,
            emitter=emitter_name,
            scenario_id=scenario_id,
            app="logops",
            source="ingest",
        )

        # 4) Rozkład leveli
        level_counts = Counter()
        for n in normalized:
            lvl = (n.get("level") or "UNKNOWN").upper().strip()
            level_counts[lvl] += 1

        logger.info(
            "[ingest] emitter=%s scenario_id=%s accepted=%d missing_ts=%d missing_level=%d enc=%s",
            emitter_name,
            scenario_id,
            len(normalized),
            counters["missing_ts"],
            counters["missing_level"],
            bool(globals().get("ENCRYPT_PII", False)),
        )

        # 5) Zapis NDJSON (Promtail) — kontrolowany flagą
        try:
            sink_enabled = bool(SINK_FILE)  # default z metrics.py
            # pozwól nadpisać katalog przez env (kompatybilność ze smoke)
            sink_dir_path = os.getenv("LOGOPS_SINK_DIR", SINK_DIR_PATH or "./data/ingest")

            if sink_enabled and normalized:
                from pathlib import Path

                sink_dir = Path(sink_dir_path)
                sink_dir.mkdir(parents=True, exist_ok=True)
                day = datetime.now(UTC).strftime("%Y%m%d")
                out_file = sink_dir / f"{day}.ndjson"
                with out_file.open("a", encoding="utf-8") as fh:
                    for n in normalized:
                        fh.write(
                            json.dumps(
                                {k: v for k, v in n.items() if not k.startswith("_")},
                                ensure_ascii=False,
                            )
                            + "\n"
                        )
        except Exception:
            # celowo łykamy — nie blokuje ingestu
            pass

        # 6) Metryki Prometheus
        try:
            BATCH_SIZE.observe(len(normalized))  # type: ignore[name-defined]
            BATCH_LATENCY.labels(emitter_name, scenario_id).observe(  # type: ignore[name-defined]
                time.perf_counter() - t0
            )
            if normalized:
                ACCEPTED_TOTAL.labels(emitter_name, scenario_id).inc(  # type: ignore[name-defined]
                    len(normalized)
                )
            for lvl, cnt in level_counts.items():
                INGESTED_TOTAL.labels(emitter=emitter_name, level=lvl).inc(  # type: ignore[name-defined]
                    cnt
                )
            if counters["missing_ts"]:
                MISSING_TS_TOTAL.labels(emitter_name, scenario_id).inc(  # type: ignore[name-defined]
                    counters["missing_ts"]
                )
            if counters["missing_level"]:
                MISSING_LEVEL_TOTAL.labels(emitter_name, scenario_id).inc(  # type: ignore[name-defined]
                    counters["missing_level"]
                )
        except Exception:
            pass

        # 7) Forward do Core (8095) – przekazujemy nagłówki transportowe
        core_headers = {
            "Content-Type": "application/json",
            "X-Emitter": emitter_name,
            "X-Scenario-Id": scenario_id,
        }
        try:
            resp = await _post_with_retry(
                CORE_URL,
                json_payload=normalized,
                headers=core_headers,
                attempts=3,
                base_delay_ms=100,
                max_delay_ms=1500,
                connect_s=2.0,
                read_s=5.0,
                write_s=5.0,
                pool_s=2.0,
            )
            try:
                content = resp.json()
            except Exception:
                content = {"downstream_text": resp.text}
            return JSONResponse(content, status_code=resp.status_code)
        except RuntimeError as e:
            raise HTTPException(status_code=502, detail=str(e)) from e

    finally:
        try:
            METRIC_INFLIGHT.dec()  # type: ignore[name-defined]
        except Exception:
            pass
