from fastapi import FastAPI, Request
from datetime import datetime, timezone
from typing import Any

VERSION = "v3-request-body"

app = FastAPI(title=f"LogOps Ingest Gateway ({VERSION})")
gateway = app  # alias

@app.get("/healthz")
async def healthz():
    return {"status": "ok", "version": VERSION}

@app.post("/v1/logs")
async def ingest_logs(request: Request):
    # CZYTAMY SUROWE BODY JAKO JSON (DZIAŁA DLA dict I list[dict])
    payload: Any = await request.json()
    accepted = len(payload) if isinstance(payload, list) else 1
    return {"accepted": accepted, "ts": datetime.now(timezone.utc).isoformat()}
