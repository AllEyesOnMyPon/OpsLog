import logging
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, List
from fastapi import FastAPI, Request, HTTPException
from json import JSONDecodeError

VERSION = "v4-normalize"
app = FastAPI(title=f"LogOps Ingest Gateway ({VERSION})")

# logger
logger = logging.getLogger("gateway")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

LEVEL_MAP = {
    "debug": "DEBUG", "info": "INFO",
    "warn": "WARN", "warning": "WARN",
    "error": "ERROR", "fatal": "ERROR",
}

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

    msg = rec.get("message") or rec.get("msg") or rec.get("log") or ""

    return {"ts": ts_out, "level": lvl_norm, "msg": str(msg),
            "_missing_ts": missing_ts, "_missing_level": missing_level}

@app.get("/healthz")
async def healthz():
    return {"status": "ok", "version": VERSION}

@app.post("/v1/logs")
async def ingest_logs(request: Request):
    try:
        payload: Any = await request.json()
    except JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    records: List[Dict[str, Any]]
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

    return {"accepted": len(records),
            "ts": datetime.now(timezone.utc).isoformat(),
            "missing_ts": counters["missing_ts"],
            "missing_level": counters["missing_level"]}
