import os
import re
import csv
import json
import logging
from io import StringIO
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib import response

from fastapi import FastAPI, Request, HTTPException, Response
from fastapi.responses import JSONResponse
from json import JSONDecodeError

from pathlib import Path
from dotenv import load_dotenv, dotenv_values
from cryptography.fernet import Fernet

import asyncio
from contextlib import suppress
from contextlib import asynccontextmanager

from prometheus_client import Counter as PromCounter, Gauge, generate_latest, CONTENT_TYPE_LATEST

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
METRIC_ACCEPTED = PromCounter("logops_accepted_total", "Total number of accepted logs")
METRIC_MISSING_TS = PromCounter("logops_missing_ts_total", "Logs missing timestamp")
METRIC_MISSING_LEVEL = PromCounter("logops_missing_level_total", "Logs missing level")
METRIC_INFLIGHT = Gauge("logops_inflight", "Logs currently being processed")

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
    PROJECT_ROOT, DOTENV_PATH, bool(SECRET_KEY), ENCRYPT_PII, ENCRYPT_FIELDS, SINK_FILE
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
IP_RE = re.compile(r'\b(\d{1,3}\.){3}\d{1,3}\b')

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
    rest = re.sub(r"^\S+\s+\S+\[\d+\]:\s*", "", rest)
    return {"ts": ts, "level": level, "message": rest}

def parse_csv_text_body(text: str) -> List[Dict[str, Any]]:
    buf = StringIO(text)
    reader = csv.DictReader(buf)
    out: List[Dict[str, Any]] = []
    for row in reader:
        out.append({
            "ts": row.get("ts") or row.get("time") or row.get("timestamp"),
            "level": row.get("level") or row.get("lvl") or row.get("severity"),
            "message": row.get("msg") or row.get("message") or row.get("log"),
            "user_email": row.get("user_email"),
            "client_ip": row.get("client_ip"),
        })
    return out

# ========= Normalization =========
def normalize_record(rec: Dict[str, Any]) -> Dict[str, Any]:
    ts = rec.get("ts") or rec.get("timestamp") or rec.get("time")
    ts_out = str(ts) if ts else datetime.now(timezone.utc).isoformat()
    missing_ts = ts is None

    lvl_in = rec.get("level") or rec.get("lvl") or rec.get("severity") or "INFO"
    lvl_norm = LEVEL_MAP.get(str(lvl_in).lower(), "INFO")
    missing_level = not any(k in rec for k in ["level", "lvl", "severity"])

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

from fastapi.responses import JSONResponse  # jeśli chcesz jawnie

@app.post("/v1/logs")
async def ingest_logs(request: Request):
    METRIC_INFLIGHT.inc()
    try:
        content_type = (request.headers.get("content-type") or "").lower()

        # 1) Parsowanie body -> records
        if content_type.startswith("text/plain"):
            text = (await request.body()).decode("utf-8", errors="replace")
            records: List[Dict[str, Any]] = [parse_syslog_line(ln) for ln in text.splitlines() if ln.strip()]
        elif content_type.startswith("text/csv"):
            text = (await request.body()).decode("utf-8", errors="replace")
            records = parse_csv_text_body(text)
        else:
            try:
                payload: Any = await request.json()
            except JSONDecodeError:
                raise HTTPException(status_code=400, detail="Invalid JSON body")
            if isinstance(payload, list):
                records = payload
            elif isinstance(payload, dict):
                records = [payload]
            else:
                raise HTTPException(status_code=400, detail="Payload must be object or array of objects")

        # 2) Doklej emitter z nagłówka (fallback tylko nagłówek; w payloadzie może już być)
        emitter_name = (request.headers.get("X-Emitter") or "").strip() or None
        if emitter_name:
            def attach_emitter(rec: Dict[str, Any]) -> Dict[str, Any]:
                if isinstance(rec, dict) and "emitter" not in rec:
                    rec["emitter"] = emitter_name
                return rec
            records = [attach_emitter(r if isinstance(r, dict) else {}) for r in records]

        # 3) Normalizacja + liczniki + próbka
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

        logger.info(
            "[ingest] accepted=%d missing_ts=%d missing_level=%d enc=%s",
            len(records), counters["missing_ts"], counters["missing_level"], ENCRYPT_PII
        )

        # 4) Opcjonalny zapis NDJSON (bez pól technicznych)
        if SINK_FILE and normalized:
            day = datetime.now(timezone.utc).strftime("%Y%m%d")
            out_file = SINK_DIR_PATH / f"{day}.ndjson"
            with out_file.open("a", encoding="utf-8") as fh:
                for n in normalized:
                    fh.write(json.dumps({k: v for k, v in n.items() if not k.startswith("_")}, ensure_ascii=False) + "\n")

        # 5) Odpowiedź + metryki
        response = {
            "accepted": len(records),
            "ts": datetime.now(timezone.utc).isoformat(),
            "missing_ts": counters["missing_ts"],
            "missing_level": counters["missing_level"],
        }
        if DEBUG_SAMPLE and sample:
            response["sample"] = sample

        METRIC_ACCEPTED.inc(len(records))
        if counters["missing_ts"]:
            METRIC_MISSING_TS.inc(counters["missing_ts"])
        if counters["missing_level"]:
            METRIC_MISSING_LEVEL.inc(counters["missing_level"])

        return JSONResponse(response)
    finally:
        METRIC_INFLIGHT.dec()


@app.get("/metrics")
async def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)