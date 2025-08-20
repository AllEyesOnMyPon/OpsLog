# ... importy u góry pliku:
import logging, re
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, List
from fastapi import FastAPI, Request, HTTPException
from json import JSONDecodeError

VERSION = "v5-text-support"
app = FastAPI(title=f"LogOps Ingest Gateway ({VERSION})")
logger = logging.getLogger("gateway")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

LEVEL_MAP = {
    "debug": "DEBUG", "info": "INFO",
    "warn": "WARN", "warning": "WARN",
    "error": "ERROR", "fatal": "ERROR",
}

# prościutki parser syslog-like:
SYSLOG_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\s+(?P<level>[A-Z]+)?\s*(?P<rest>.*)$"
)

def parse_syslog_line(line: str) -> Dict[str, Any]:
    m = SYSLOG_RE.match(line.strip())
    if not m:
        return {"msg": line.strip()}
    gd = m.groupdict()
    ts = gd.get("ts")
    level = gd.get("level") or "INFO"
    rest = gd.get("rest") or ""
    # usuń ewentualny prefix "host app[pid]: "
    rest = re.sub(r"^\S+\s+\S+\[\d+\]:\s*", "", rest)
    return {"ts": ts, "level": level, "message": rest}

def normalize_record(rec: Dict[str, Any]) -> Dict[str, Any]:
    ts = rec.get("ts") or rec.get("timestamp") or rec.get("time")
    if ts is None:
        ts_out = datetime.now(timezone.utc).isoformat()
        missing_ts = True
    else:
        ts_out = str(ts)
        missing_ts = False

    lvl_in = rec.get("level") or rec.get("lvl") or rec.get("severity") or "INFO"
    lvl_norm = LEVEL_MAP.get(str(lvl_in).lower(), "INFO")
    missing_level = "level" not in rec and "lvl" not in rec and "severity" not in rec

    msg = rec.get("message") or rec.get("msg") or rec.get("log") or rec.get("raw") or ""

    return {"ts": ts_out, "level": lvl_norm, "msg": str(msg),
            "_missing_ts": missing_ts, "_missing_level": missing_level}

@app.get("/healthz")
async def healthz():
    return {"status": "ok", "version": VERSION}

@app.post("/v1/logs")
async def ingest_logs(request: Request):
    content_type = (request.headers.get("content-type") or "").lower()

    records: List[Dict[str, Any]] = []

    if content_type.startswith("text/plain"):
        # tryb: linie tekstowe → parsujemy każdą
        body_bytes = await request.body()
        text = body_bytes.decode("utf-8", errors="replace")
        lines = [ln for ln in text.splitlines() if ln.strip()]
        for ln in lines:
            records.append(parse_syslog_line(ln))
    else:
        # tryb: JSON (object lub array)
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

    counters = Counter()
    for rec in records:
        norm = normalize_record(rec if isinstance(rec, dict) else {})
        if norm["_missing_ts"]:
            counters["missing_ts"] += 1
        if norm["_missing_level"]:
            counters["missing_level"] += 1

    logger.info("[ingest] accepted=%d missing_ts=%d missing_level=%d",
                len(records), counters["missing_ts"], counters["missing_level"])

    return {
        "accepted": len(records),
        "ts": datetime.now(timezone.utc).isoformat(),
        "missing_ts": counters["missing_ts"],
        "missing_level": counters["missing_level"],
    }
