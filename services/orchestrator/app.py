from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from .models import ListResponse, StartRequest, StartResponse, StopRequest
from .runner import ORCH, to_info

app = FastAPI(title="LogOps Orchestrator", version="0.1.0")


@app.get("/healthz")
async def healthz():
    return {"ok": True, "running": len((await ORCH.list()).keys())}


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/scenario/list", response_model=ListResponse)
async def list_scenarios():
    items = [to_info(sp) for sp in (await ORCH.list()).values()]
    return ListResponse(items=items)


@app.post("/scenario/start", response_model=StartResponse)
async def start_scenario(req: StartRequest):
    try:
        sp = await ORCH.start(req)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return StartResponse(
        scenario_id=sp.scenario_id,
        status=sp.status,
        name=sp.name,
        log_file=sp.log_file,
    )


@app.post("/scenario/stop")
async def stop_scenario(req: StopRequest):
    ok = await ORCH.stop(req.scenario_id)
    if not ok:
        raise HTTPException(status_code=404, detail="not found or already stopped")
    return JSONResponse({"stopped": True, "scenario_id": req.scenario_id})


# Łatwy punkt startowy (dev):
#   uvicorn services.orchestrator.app:app --port 8070 --reload
