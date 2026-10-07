"""API del injector (para el botón de la demo y las evals).

No usa `create_app` de los servicios a propósito: sus logs y métricas no deben
llegar a Loki ni a Prometheus, porque el agente podría leer ahí la respuesta.
"""

import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel
from redis.asyncio import Redis

from incilot_sim.agent_access import ensure_postgres_access
from incilot_sim.company_repo import build
from incilot_sim.injector import scenarios
from incilot_sim.injector.core import InjectionError, Injector, connect_groundtruth

DATA = Path(os.getenv("INJECTOR_DATA", "../incilot-data"))
COMPANY_REPO = Path(os.getenv("COMPANY_REPO", "build/company-repo"))
# Token del ejecutor de acciones aprobadas (lo tiene solo el worker del agente).
OPS_TOKEN = os.getenv("OPS_TOKEN")

injector: Injector


class InjectionRequest(BaseModel):
    scenario: str
    variant: str | None = None


@asynccontextmanager
async def lifespan(_):
    global injector
    if not (COMPANY_REPO / ".git").exists():
        build(DATA, COMPANY_REPO, datetime.now(UTC))
    db = await connect_groundtruth(os.environ["GROUNDTRUTH_DATABASE_URL"])
    await ensure_postgres_access(os.environ["GROUNDTRUTH_DATABASE_URL"])
    redis = Redis.from_url(os.environ["FAULTS_REDIS_URL"], decode_responses=True)
    injector = Injector(db, redis, DATA, COMPANY_REPO, os.environ["GROUNDTRUTH_DATABASE_URL"])
    yield
    await injector.aclose()


app = FastAPI(title="injector", lifespan=lifespan)


class ActionRequest(BaseModel):
    kind: str
    target: str


@app.post("/ops/execute")
async def execute(request: ActionRequest, x_ops_token: str | None = Header(default=None)):
    """Ejecuta una acción aprobada por un humano. Solo con el token de operaciones."""
    if not OPS_TOKEN or x_ops_token != OPS_TOKEN:
        raise HTTPException(403, "token de operaciones inválido")
    return await injector.execute_action(request.kind, request.target)


@app.get("/scenarios")
async def list_scenarios():
    return {
        scenario_id: {
            "title": variants[0].title,
            "category": variants[0].category,
            "variants": [
                {"variant": v.id, "service": v.service, "split": v.split} for v in variants
            ],
        }
        for scenario_id, variants in scenarios.load(DATA).items()
    }


@app.get("/injections")
async def list_injections(limit: int = 20):
    return await injector.history(limit)


@app.get("/injections/active")
async def active_injection():
    if active := await injector.active():
        return active
    raise HTTPException(404, "no hay ninguna inyección activa")


@app.post("/injections", status_code=201)
async def inject(request: InjectionRequest):
    try:
        variant = scenarios.pick(scenarios.load(DATA), request.scenario, request.variant)
    except KeyError as exc:
        raise HTTPException(404, exc.args[0]) from None
    try:
        return await injector.inject(variant)
    except InjectionError as exc:
        raise HTTPException(409, str(exc)) from None


@app.post("/injections/active/recover")
async def recover():
    try:
        return await injector.recover()
    except InjectionError as exc:
        raise HTTPException(409, str(exc)) from None
