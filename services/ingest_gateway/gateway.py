import os
import re
import csv
import logging
from io import StringIO
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, Request, HTTPException
from json import JSONDecodeError

from pathlib import Path
from dotenv import load_dotenv, dotenv_values
from cryptography.fernet import Fernet

# === Load config ===
PROJECT_ROOT = Path(__file__).resolve().parents[2]  # .../logops
DOTENV_PATH = PROJECT_ROOT / ".env"

# 1) Załaduj do os.environ (z nadpisaniem)
load_dotenv(dotenv_path=DOTENV_PATH, override=True)

# 2) Równolegle wczytaj bezpośrednio do dict (na wypadek problemów z os.environ)
_cfg = {}
try:
    _cfg = dotenv_values(DOTENV_PATH)
except Exception:
    _cfg = {}

VERSION = "v7-pii-encryption"
app = FastAPI(title=f"LogOps Ingest Gateway ({VERSION})")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("gateway")

# --- Environment configuration ---
# próbuj najpierw z os.environ, potem z pliku .env (dict)
SECRET_KEY = os.getenv("LOGOPS_SECRET_KEY") or _cfg.get("LOGOPS_SECRET_KEY")
ENCRYPT_PII = (os.getenv("LOGOPS_ENCRYPT_PII") or _cfg.get("LOGOPS_ENCRYPT_PII") or "false").lower() == "true"
ENCRYPT_FIELDS = (os.getenv("LOGOPS_ENCRYPT_FIELDS") or _cfg.get("LOGOPS_ENCRYPT_FIELDS") or "user_email,client_ip")
ENCRYPT_FIELDS = [f.strip() for f in ENCRYPT_FIELDS.split(",") if f.strip()]
DEBUG_SAMPLE = (os.getenv("LOGOPS_DEBUG_SAMPLE") or _cfg.get("LOGOPS_DEBUG_SAMPLE") or "false").lower() == "true"
DEBUG_SAMPLE_SIZE = int(os.getenv("LOGOPS_DEBUG_SAMPLE_SIZE") or _cfg.get("LOGOPS_DEBUG_SAMPLE_SIZE") or "2")

# krótka telemetria startowa
logger.info("ENV check: root=%s, dotenv=%s, has_key=%s, encrypt_pii=%s, fields=%s",
            PROJECT_ROOT, DOTENV_PATH, bool(SECRET_KEY), ENCRYPT_PII, ENCRYPT_FIELDS)

fernet: Optional[Fernet] = None
if ENCRYPT_PII:
    if not SECRET_KEY:
        logger.warning("PII encryption enabled but no LOGOPS_SECRET_KEY set; disabling encryption.")
        ENCRYPT_PII = False
    else:
        fernet = Fernet(SECRET_KEY)

# --- diagnostics ---
print("=== DEBUG ENV ===")
print("LOGOPS_SECRET_KEY:", os.getenv("LOGOPS_SECRET_KEY"))
print("ENCRYPT_PII (raw):", os.getenv("LOGOPS_ENCRYPT_PII"))
print("ENCRYPT_FIELDS:", os.getenv("LOGOPS_ENCRYPT_FIELDS"))
print("=================")

VERSION = "v7-pii-encryption"
app = FastAPI(title=f"LogOps Ingest Gateway ({VERSION})")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
logger = logging.getLogger("gateway")

# --- Environment configuration ---
SECRET_KEY = os.getenv("LOGOPS_SECRET_KEY")
ENCRYPT_PII = os.getenv("LOGOPS_ENCRYPT_PII", "false").lower() == "true"
ENCRYPT_FIELDS = [
    f.strip() for f in os.getenv("LOGOPS_ENCRYPT_FIELDS", "user_email,client_ip").split(",")
    if f.strip()
]
DEBUG_SAMPLE = os.getenv("LOGOPS_DEBUG_SAMPLE", "false").lower() == "true"
DEBUG_SAMPLE_SIZE = int(os.getenv("LOGOPS_DEBUG_SAMPLE_SIZE", "2"))

fernet: Optional[Fernet] = None
if ENCRYPT_PII:
    if not SECRET_KEY:
        logger.warning("PII encryption enabled but no LOGOPS_SECRET_KEY set; disabling encryption.")
        ENCRYPT_PII = False
    else:
        fernet = Fernet(SECRET_KEY)

# --- Regex & mappings ---
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


# === PII helpers ===
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


# === Parsers ===
def parse_syslog_line(line: str) -> Dict[str, Any]:
    """Parses a syslog-style line into dict"""
    m = SYSLOG_RE.match(line.strip())
    if not m:
        return {"msg": line.strip()}

    gd = m.groupdict()
    ts = gd.get("ts")
    level = gd.get("level") or "INFO"
    rest = gd.get("rest") or ""

    # strip "program[pid]: " prefix if present
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


# === Normalization ===
def normalize_record(rec: Dict[str, Any]) -> Dict[str, Any]:
    # timestamp
    ts = rec.get("ts") or rec.get("timestamp") or rec.get("time")
    ts_out = str(ts) if ts else datetime.now(timezone.utc).isoformat()
    missing_ts = ts is None

    # level
    lvl_in = rec.get("level") or rec.get("lvl") or rec.get("severity") or "INFO"
    lvl_norm = LEVEL_MAP.get(str(lvl_in).lower(), "INFO")
    missing_level = not any(k in rec for k in ["level", "lvl", "severity"])

    # message
    raw_msg = rec.get("message") or rec.get("msg") or rec.get("log") or rec.get("raw") or ""
    msg_masked = mask_pii(str(raw_msg))

    norm = {
        "ts": ts_out,
        "level": lvl_norm,
        "msg": msg_masked,
        "_missing_ts": missing_ts,
        "_missing_level": missing_level,
    }

    # --- optional encryption ---
    if ENCRYPT_PII and fernet:
        if str(raw_msg):
            norm["msg_enc"] = encrypt_str(str(raw_msg))

        for key in ENCRYPT_FIELDS:
            if key in rec and rec[key]:
                norm[f"{key}_enc"] = encrypt_str(str(rec[key]))

        # overwrite original fields with masked values
        if "user_email" in rec and rec["user_email"]:
            norm["user_email"] = mask_email(str(rec["user_email"]))
        if "client_ip" in rec and rec["client_ip"]:
            norm["client_ip"] = mask_ip(str(rec["client_ip"]))

    return norm


# === API endpoints ===
@app.get("/healthz")
async def healthz():
    return {
        "status": "ok",
        "version": VERSION,
        "pii_encryption": ENCRYPT_PII,
    }


@app.post("/v1/logs")
async def ingest_logs(request: Request):
    content_type = (request.headers.get("content-type") or "").lower()
    records: List[Dict[str, Any]] = []

    # --- Parse request depending on content type ---
    if content_type.startswith("text/plain"):
        text = (await request.body()).decode("utf-8", errors="replace")
        records = [parse_syslog_line(ln) for ln in text.splitlines() if ln.strip()]
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

    # --- Normalize + counters ---
    counters = Counter()
    sample: List[Dict[str, Any]] = []

    for rec in records:
        norm = normalize_record(rec if isinstance(rec, dict) else {})
        if norm["_missing_ts"]:
            counters["missing_ts"] += 1
        if norm["_missing_level"]:
            counters["missing_level"] += 1
        if DEBUG_SAMPLE and len(sample) < DEBUG_SAMPLE_SIZE:
            sample.append({k: v for k, v in norm.items() if not k.startswith("_")})

    logger.info(
        "[ingest] accepted=%d missing_ts=%d missing_level=%d enc=%s",
        len(records), counters["missing_ts"], counters["missing_level"], ENCRYPT_PII
    )

    # --- Response ---
    response = {
        "accepted": len(records),
        "ts": datetime.now(timezone.utc).isoformat(),
        "missing_ts": counters["missing_ts"],
        "missing_level": counters["missing_level"],
    }
    if DEBUG_SAMPLE and sample:
        response["sample"] = sample

    return response
