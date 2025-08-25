import os
import re
import csv
import json
import time
import logging
from io import StringIO
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pathlib import Path
from dotenv import load_dotenv, dotenv_values
from cryptography.fernet import Fernet
from pydantic import BaseModel, ValidationError

import asyncio
from contextlib import suppress
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException, Response
from fastapi.responses import JSONResponse
from json import JSONDecodeError

from prometheus_client import (
    Counter as PromCounter,
    Gauge,
    Histogram,
    generate_latest,
    CONTENT_TYPE_LATEST,
)

# ========= Config & ENV =========
PROJECT_ROOT = Path(__file__).resolve().parents[2]  # .../logops
DOTENV_PATH = PROJECT_ROOT / ".env"

load_dotenv(dotenv_path=DOTENV_PATH, override=True)
_cfg = {}
try:
    _cfg = dotenv_values(DOTENV_PATH)
except Exception:
    _cfg = {}


def _getenv(name: str, default: Optional[str] = None) -> Optional[str]:
    val = os.getenv(name)
    if val is not None:
        return val
    return _cfg.get(name, default)


VERSION = "v7-pii-encryption"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("gateway")

# ========= Prometheus metrics =========
# Inflight — ile żądań /v1/logs jest aktualnie przetwarzanych
METRIC_INFLIGHT = Gauge("logops_inflight", "Logs currently being processed")

# Liczniki per emitter/level
INGESTED_TOTAL = PromCounter(
    "logops_ingested_total",
    "Number of ingested log records",
    ["emitter", "level"],
)

# Braki pól per emitter
MISSING_TS_TOTAL = PromCounter(
    "logops_missing_ts_total",
    "Records missing timestamp after parsing/normalization",
    ["emitter"],
)
MISSING_LEVEL_TOTAL = PromCounter(
    "logops_missing_level_total",
    "Records missing level after parsing/normalization",
    ["emitter"],
)

# Błędy walidacji (JSON)
PARSE_ERRORS = PromCounter(
    "logops_parse_errors_total",
    "Number of records rejected during input validation",
    ["emitter"],
)

# Histogramy batcha
BATCH_SIZE = Histogram(
    "logops_batch_size",
    "Size of incoming batches (number of records)",
    buckets=(1, 5, 10, 20, 50, 100, 200, 500),
)
BATCH_LATENCY = Histogram(
    "logops_batch_latency_seconds",
    "Processing time for a batch, seconds",
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5),
)

# Metryki per-scenario
INGESTED_SCENARIO_TOTAL = PromCounter(
    "logops_ingested_scenario_total",
    "Number of ingested log records, by scenario",
    ["emitter", "level", "scenario"],
)
MISSING_TS_SCENARIO_TOTAL = PromCounter(
    "logops_missing_ts_scenario_total",
    "Records missing timestamp by scenario",
    ["emitter", "scenario"],
)
MISSING_LEVEL_SCENARIO_TOTAL = PromCounter(
    "logops_missing_level_scenario_total",
    "Records missing level by scenario",
    ["emitter", "scenario"],
)

# ========= PII / env flags =========
SECRET_KEY = _getenv("LOGOPS_SECRET_KEY")
ENCRYPT_PII = (_getenv("LOGOPS_ENCRYPT_PII", "false") or "false").lower() == "true"
_encrypted_fields_raw = _getenv("LOGOPS_ENCRYPT_FIELDS", "user_email,client_ip") or ""
ENCRYPT_FIELDS = [f.strip() for f in _encrypted_fields_raw.split(",") if f.strip()]
DEBUG_SAMPLE = (_getenv("LOGOPS_DEBUG_SAMPLE", "false") or "false").lower() == "true"
DEBUG_SAMPLE_SIZE = int(_getenv("LOGOPS_DEBUG_SAMPLE_SIZE", "2") or "2")

SINK_FILE = (_getenv("LOGOPS_SINK_FILE", "false") or "false").lower() == "true"
SINK_DIR = _getenv("LOGOPS_SINK_DIR", "./data/ingest") or "./data/ingest"
SINK_DIR_PATH = (PROJECT_ROOT / SINK_DIR).resolve()
if SINK_FILE:
    SINK_DIR_PATH.mkdir(parents=True, exist_ok=True)

HOUSEKEEP_AUTORUN = (_getenv("LOGOPS_HOUSEKEEP_AUTORUN", "false") or "false").lower() == "true"
HOUSEKEEP_INTERVAL = int(_getenv("LOGOPS_HOUSEKEEP_INTERVAL_SEC", "0") or "0")

try:
    from tools.housekeeping import run_once as hk_run_once
except Exception:
    hk_run_once = None

fernet: Optional[Fernet] = None
if ENCRYPT_PII:
    if not SECRET_KEY:
        logger.warning("PII encryption enabled but no LOGOPS_SECRET_KEY set; disabling encryption.")
        ENCRYPT_PII = False
    else:
        fernet = Fernet(SECRET_KEY)

logger.info(
    "ENV check: root=%s, dotenv=%s, has_key=%s, encrypt_pii=%s, fields=%s, sink=%s",
    PROJECT_ROOT,
    DOTENV_PATH,
    bool(SECRET_KEY),
    ENCRYPT_PII,
    ENCRYPT_FIELDS,
    SINK_FILE,
)

# ========= Housekeeping loop =========
async def _hk_loop():
    while True:
        try:
            if hk_run_once:
                hk_run_once()
                logger.info("[housekeep] run_once completed")
        except Exception:
            logger.exception("[housekeep] error during periodic run")
        await asyncio.sleep(HOUSEKEEP_INTERVAL)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # startup
    if HOUSEKEEP_AUTORUN and hk_run_once:
        try:
            hk_run_once()
            logger.info("[housekeep] run_once at startup done")
        except Exception:
            logger.exception("[housekeep] startup housekeeping failed")
        if HOUSEKEEP_INTERVAL > 0:
            app.state.hk_task = asyncio.create_task(_hk_loop())
            logger.info("[housekeep] periodic loop started: %ss", HOUSEKEEP_INTERVAL)
    yield
    # shutdown
    task = getattr(app.state, "hk_task", None)
    if task:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


app = FastAPI(title=f"LogOps Ingest Gateway ({VERSION})", lifespan=lifespan)

# ========= Regex & mappings =========
LEVEL_MAP = {
    "debug": "DEBUG",
    "info": "INFO",
    "warn": "WARN",
    "warning": "WARN",
    "error": "ERROR",
    "fatal": "ERROR",
}

SYSLOG_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\s+(?P<level>[A-Z]+)?\s*(?P<rest>.*)$"
)
EMAIL_RE = re.compile(r'([A-Za-z0-9._%+-])([A-Za-z0-9._%+-]*)(@[^,\s"]+)')
IP_RE = re.compile(r"\b(\d{1,3}\.){3}\d{1,3}\b")

# ========= Pydantic „miękka” walidacja JSON =========
class LogRecordIn(BaseModel):
    ts: Optional[Any] = None
    timestamp: Optional[Any] = None
    time: Optional[Any] = None
    level: Optional[Any] = None
    lvl: Optional[Any] = None
    severity: Optional[Any] = None
    message: Optional[Any] = None
    msg: Optional[Any] = None
    log: Optional[Any] = None
    user_email: Optional[Any] = None
    client_ip: Optional[Any] = None
    emitter: Optional[str] = None

    class Config:
        extra = "allow"


# ========= PII helpers =========
def mask_email(s: str) -> str:
    def _m(m: re.Match) -> str:
        first, domain = m.group(1), m.group(3)
        return f"{first}***{domain}"

    return EMAIL_RE.sub(_m, s)


def mask_ip(s: str) -> str:
    return IP_RE.sub(lambda m: ".".join(m.group(0).split(".")[:2] + ["x", "x"]), s)


def mask_pii(s: str) -> str:
    return mask_ip(mask_email(s))


def encrypt_str(value: str) -> str:
    if ENCRYPT_PII and fernet:
        return fernet.encrypt(value.encode("utf-8")).decode("utf-8")
    return value


# ========= Parsers =========
def parse_syslog_line(line: str) -> Dict[str, Any]:
    m = SYSLOG_RE.match(line.strip())
    if not m:
        return {"msg": line.strip()}
    gd = m.groupdict()
    ts = gd.get("ts")
    level = gd.get("level") or "INFO"
    rest = gd.get("rest") or ""
    # usuń prefix "host app[pid]:" jeśli jest
    rest = re.sub(r"^\S+\s+\S+\[\d+\]:\s*", "", rest)
    return {"ts": ts, "level": level, "message": rest}


def parse_csv_text_body(text: str) -> List[Dict[str, Any]]:
    buf = StringIO(text)
    reader = csv.DictReader(buf)
    out: List[Dict[str, Any]] = []
    for row in reader:
        out.append(
            {
                "ts": row.get("ts") or row.get("time") or row.get("timestamp"),
                "level": row.get("level") or row.get("lvl") or row.get("severity"),
                "message": row.get("msg") or row.get("message") or row.get("log"),
                "user_email": row.get("user_email"),
                "client_ip": row.get("client_ip"),
            }
        )
    return out


# ========= Normalization =========
def normalize_record(rec: Dict[str, Any]) -> Dict[str, Any]:
    # --- ts ---
    ts_val = None
    for k in ("ts", "timestamp", "time"):
        v = rec.get(k)
        if v is not None and str(v).strip() != "":
            ts_val = v
            break
    missing_ts = ts_val is None
    ts_out = str(ts_val) if ts_val is not None else datetime.now(timezone.utc).isoformat()

    # --- level ---
    lvl_raw = None
    for k in ("level", "lvl", "severity"):
        v = rec.get(k)
        if v is not None and str(v).strip() != "":
            lvl_raw = v
            break
    missing_level = (lvl_raw is None)
    lvl_norm = LEVEL_MAP.get(str(lvl_raw).lower(), "INFO") if lvl_raw is not None else "INFO"

    # --- message ---
    raw_msg = rec.get("message") or rec.get("msg") or rec.get("log") or rec.get("raw") or ""
    msg_masked = mask_pii(str(raw_msg))

    norm = {
        "ts": ts_out,
        "level": lvl_norm,
        "msg": msg_masked,
        "_missing_ts": missing_ts,
        "_missing_level": missing_level,
    }

    if "emitter" in rec and rec["emitter"]:
        norm["emitter"] = str(rec["emitter"])

    if ENCRYPT_PII and fernet:
        if str(raw_msg):
            norm["msg_enc"] = encrypt_str(str(raw_msg))
        for key in ENCRYPT_FIELDS:
            if key in rec and rec[key]:
                norm[f"{key}_enc"] = encrypt_str(str(rec[key]))
        if "user_email" in rec and rec["user_email"]:
            norm["user_email"] = mask_email(str(rec["user_email"]))
        if "client_ip" in rec and rec["client_ip"]:
            norm["client_ip"] = mask_ip(str(rec["client_ip"]))

    return norm

# ========= API =========
@app.get("/healthz")
async def healthz():
    return {
        "status": "ok",
        "version": VERSION,
        "pii_encryption": ENCRYPT_PII,
        "file_sink": SINK_FILE,
        "file_sink_dir": str(SINK_DIR_PATH) if SINK_FILE else None,
    }


@app.get("/metrics")
async def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/v1/logs")
async def ingest_logs(request: Request):
    METRIC_INFLIGHT.inc()
    t0 = time.time()
    try:
        content_type = (request.headers.get("content-type") or "").lower()
        emitter_name = (request.headers.get("X-Emitter") or "").strip() or "unknown"
        scenario_name = (request.headers.get("X-Scenario") or "").strip() or "none"

        # 1) Body -> records
        if content_type.startswith("text/plain"):
            # syslog-like: zwykły tekst, każda linia -> rekord
            text = (await request.body()).decode("utf-8", errors="replace")
            records: List[Dict[str, Any]] = [
                parse_syslog_line(ln) for ln in text.splitlines() if ln.strip()
            ]
        elif content_type.startswith("text/csv"):
            # CSV z nagłówkiem: ts,level,msg[,user_email,client_ip]
            text = (await request.body()).decode("utf-8", errors="replace")
            records = parse_csv_text_body(text)
        else:
            # JSON (pojedynczy obiekt lub tablica obiektów)
            try:
                payload: Any = await request.json()
            except JSONDecodeError:
                raise HTTPException(status_code=400, detail="Invalid JSON body")

            if isinstance(payload, list):
                records = payload
            elif isinstance(payload, dict):
                records = [payload]
            else:
                raise HTTPException(
                    status_code=400,
                    detail="Payload must be object or array of objects",
                )

            # Walidacja Pydantikiem – miękka (pozwalamy na extra pola)
            invalid_idx: List[int] = []
            validated: List[Dict[str, Any]] = []
            for i, item in enumerate(records):
                if not isinstance(item, dict):
                    invalid_idx.append(i)
                    continue
                try:
                    obj = LogRecordIn.model_validate(item)
                    validated.append(obj.model_dump())
                except ValidationError:
                    invalid_idx.append(i)

            if invalid_idx:
                # zliczamy błędy walidacji i zwracamy 422
                PARSE_ERRORS.labels(emitter=emitter_name).inc(len(invalid_idx))
                raise HTTPException(
                    status_code=422,
                    detail={
                        "error": "Invalid records in JSON array",
                        "invalid_indices": invalid_idx[:50],
                        "count": len(invalid_idx),
                    },
                )
            records = validated

        # 2) Doklej emitter z nagłówka (o ile w rekordzie go nie ma)
        if emitter_name:
            def attach_emitter(rec: Dict[str, Any]) -> Dict[str, Any]:
                if isinstance(rec, dict) and "emitter" not in rec:
                    rec["emitter"] = emitter_name
                return rec
            records = [attach_emitter(r if isinstance(r, dict) else {}) for r in records]

        # 3) Normalizacja + liczniki + próbka do debug
        counters = Counter()
        sample: List[Dict[str, Any]] = []
        normalized: List[Dict[str, Any]] = []

        for rec in records:
            norm = normalize_record(rec if isinstance(rec, dict) else {})
            normalized.append(norm)

            if norm.get("_missing_ts"):
                counters["missing_ts"] += 1
            if norm.get("_missing_level"):
                counters["missing_level"] += 1
            if DEBUG_SAMPLE and len(sample) < DEBUG_SAMPLE_SIZE:
                sample.append({k: v for k, v in norm.items() if not k.startswith("_")})

        # 4) Rozkład leveli (do odpowiedzi i metryk)
        level_counts = Counter()
        for n in normalized:
            lvl = (n.get("level") or "UNKNOWN").upper().strip()
            level_counts[lvl] += 1

        logger.info(
            "[ingest] emitter=%s scenario=%s accepted=%d missing_ts=%d missing_level=%d enc=%s",
            emitter_name, scenario_name, len(records),
            counters["missing_ts"], counters["missing_level"], ENCRYPT_PII
        )

        # 5) Opcjonalny zapis NDJSON (bez pól technicznych)
        if SINK_FILE and normalized:
            day = datetime.now(timezone.utc).strftime("%Y%m%d")
            out_file = SINK_DIR_PATH / f"{day}.ndjson"
            with out_file.open("a", encoding="utf-8") as fh:
                for n in normalized:
                    fh.write(
                        json.dumps(
                            {k: v for k, v in n.items() if not k.startswith("_")},
                            ensure_ascii=False
                        ) + "\n"
                    )

        # 6) Metryki Prometheus
        BATCH_SIZE.observe(len(normalized))
        BATCH_LATENCY.observe(time.time() - t0)

        # globalne per-level
        for lvl, cnt in level_counts.items():
            INGESTED_TOTAL.labels(emitter=emitter_name, level=lvl).inc(cnt)
        if counters["missing_ts"]:
            MISSING_TS_TOTAL.labels(emitter=emitter_name).inc(counters["missing_ts"])
        if counters["missing_level"]:
            MISSING_LEVEL_TOTAL.labels(emitter=emitter_name).inc(counters["missing_level"])

        # per-scenario
        for lvl, cnt in level_counts.items():
            INGESTED_SCENARIO_TOTAL.labels(
                emitter=emitter_name, level=lvl, scenario=scenario_name
            ).inc(cnt)
        if counters["missing_ts"]:
            MISSING_TS_SCENARIO_TOTAL.labels(
                emitter=emitter_name, scenario=scenario_name
            ).inc(counters["missing_ts"])
        if counters["missing_level"]:
            MISSING_LEVEL_SCENARIO_TOTAL.labels(
                emitter=emitter_name, scenario=scenario_name
            ).inc(counters["missing_level"])

        # 7) Odpowiedź
        response = {
            "accepted": len(records),
            "ts": datetime.now(timezone.utc).isoformat(),
            "emitter": emitter_name,
            "scenario": scenario_name,
            "missing_ts": counters["missing_ts"],
            "missing_level": counters["missing_level"],
            "levels": dict(level_counts),
        }
        if DEBUG_SAMPLE and sample:
            response["sample"] = sample

        return JSONResponse(response)

    finally:
        # zawsze zdejmij gauge inflight
        METRIC_INFLIGHT.dec()
