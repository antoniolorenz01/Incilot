"""API del agente: lanzar investigaciones, seguirlas en vivo (SSE) y aprobarlas.

    POST /investigations                {alert?, dry_run?}  → 202 {id}
    GET  /investigations/{id}           estado y diagnóstico
    GET  /investigations/{id}/events    eventos en vivo (Server-Sent Events)
    POST /investigations/{id}/approval  {approved, note?}

No corre el agente: encola trabajos que procesan los workers.
"""

import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from redis.asyncio import Redis

from incilot_agent import config, jobs
from incilot_agent.actions import ActionOverride
from incilot_agent.events import TERMINAL

DEFAULT_ALERT = "Se reportó una degradación en la tienda: hay quejas de clientes."
SSE_KEEPALIVE_MS = 15000

redis: Redis


class InvestigationRequest(BaseModel):
    alert: str = DEFAULT_ALERT
    dry_run: bool = False  # LLM simulado: cero tokens


class ApprovalRequest(BaseModel):
    approved: bool
    note: str = ""
    action: ActionOverride | None = None  # corregir la acción propuesta


@asynccontextmanager
async def lifespan(_):
    global redis
    redis = Redis.from_url(config.AGENT_REDIS_URL, decode_responses=True)
    yield
    await redis.aclose()


app = FastAPI(title="IncidentPilot", lifespan=lifespan)


async def _meta(investigation_id: str) -> dict:
    meta = await redis.hgetall(jobs.meta_key(investigation_id))
    if not meta:
        raise HTTPException(404, "investigación desconocida")
    return meta


@app.post("/investigations", status_code=202)
async def start(request: InvestigationRequest):
    investigation_id = uuid4().hex[:12]
    await redis.hset(
        jobs.meta_key(investigation_id),
        mapping={
            "alert": request.alert,
            "dry_run": "1" if request.dry_run else "0",
            "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        },
    )
    await jobs.enqueue(redis, {"id": investigation_id, "kind": "start", "alert": request.alert})
    return {"id": investigation_id, "status": "queued"}


@app.get("/investigations/{investigation_id}")
async def get(investigation_id: str):
    meta = await _meta(investigation_id)
    if "diagnosis" in meta:
        meta["diagnosis"] = json.loads(meta["diagnosis"])
    meta["dry_run"] = meta.get("dry_run") == "1"
    return {"id": investigation_id, **meta}


@app.get("/investigations/{investigation_id}/events")
async def events(investigation_id: str):
    await _meta(investigation_id)
    stream = jobs.events_key(investigation_id)

    async def sse():
        last_id = "0"  # desde el principio: quien se conecta tarde ve la historia
        while True:
            result = await redis.xread({stream: last_id}, block=SSE_KEEPALIVE_MS, count=100)
            if not result:
                yield ": keepalive\n\n"
                continue
            for entry_id, fields in result[0][1]:
                last_id = entry_id
                event = json.loads(fields["event"])
                yield f"id: {entry_id}\nevent: {event['type']}\ndata: {fields['event']}\n\n"
                if event["type"] in TERMINAL:
                    return

    return StreamingResponse(sse(), media_type="text/event-stream")


@app.post("/investigations/{investigation_id}/approval", status_code=202)
async def approve(investigation_id: str, request: ApprovalRequest):
    meta = await _meta(investigation_id)
    if meta.get("status") != "awaiting_approval":
        raise HTTPException(409, f"la investigación no espera aprobación ({meta.get('status')})")
    decision = {
        "approved": request.approved,
        "by": "api",
        "note": request.note,
        "action": request.action.model_dump(exclude_none=True) if request.action else None,
    }
    await jobs.enqueue(redis, {"id": investigation_id, "kind": "decision", "decision": decision})
    return {"id": investigation_id, "status": "queued"}
