from fastapi import FastAPI, Request
from datetime import datetime, timezone
from typing import Any

app = FastAPI(title="LogOps Ingest Gateway")
gateway = app  # alias

@app.get("/healthz")
async def healthz():
    return {"status": "ok"}

@app.post("/v1/logs")
async def ingest_logs(request: Request):
    """
    CZYTAMY SUROWE BODY → JSON.
    DZIAŁA DLA dict LUB list[dict].
    """
    payload: Any = await request.json()
    accepted = len(payload) if isinstance(payload, list) else 1
    return {"accepted": accepted, "ts": datetime.now(timezone.utc).isoformat()}
