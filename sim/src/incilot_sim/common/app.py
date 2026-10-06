"""Fábrica de apps FastAPI con logs de acceso, métricas, /health y /metrics."""

import logging
import os
import time
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import Depends, FastAPI, Request, Response
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from incilot_sim.common import faults, noise
from incilot_sim.common.log import configure_logging, get_logger, request_id
from incilot_sim.common.metrics import HTTP_LATENCY, HTTP_REQUESTS

_UNOBSERVED = {"/health", "/metrics"}


def create_app(service: str, lifespan=None) -> FastAPI:
    configure_logging(service, os.getenv("LOG_LEVEL", "INFO"))
    log = get_logger("http")

    @asynccontextmanager
    async def lifespan_with_faults(app: FastAPI):
        # Los fallos se detienen antes que el servicio: así sueltan las conexiones
        # retenidas antes de que se cierre el pool.
        if lifespan is None:
            async with faults.control(service):
                yield
            return
        async with lifespan(app), faults.control(service):
            yield

    app = FastAPI(
        title=service,
        lifespan=lifespan_with_faults,
        dependencies=[Depends(faults.switchboard.disrupt)]
        + ([Depends(noise.disturb)] if noise.ENABLED else []),
    )

    @app.middleware("http")
    async def observe(request: Request, call_next):
        token = request_id.set(request.headers.get("x-request-id") or uuid4().hex)
        start = time.perf_counter()
        try:
            try:
                response = await call_next(request)
            except faults.InjectedError as exc:
                # Mismo log que un error real, con el traceback que define el escenario.
                log.error(
                    "unhandled error",
                    method=request.method,
                    path=request.url.path,
                    exc=exc.traceback,
                )
                response = JSONResponse({"detail": "internal_error"}, status_code=500)
            except Exception:
                log.exception("unhandled error", method=request.method, path=request.url.path)
                response = JSONResponse({"detail": "internal_error"}, status_code=500)

            route = getattr(request.scope.get("route"), "path", "unmatched")
            if route not in _UNOBSERVED:
                elapsed = time.perf_counter() - start
                HTTP_REQUESTS.labels(request.method, route, response.status_code).inc()
                HTTP_LATENCY.labels(request.method, route).observe(elapsed)
                if response.status_code >= 500:
                    level = logging.ERROR
                elif response.status_code >= 400:
                    level = logging.WARNING
                else:
                    level = logging.INFO
                log.log(
                    level,
                    "request",
                    method=request.method,
                    path=request.url.path,
                    status=response.status_code,
                    duration_ms=round(elapsed * 1000, 1),
                )
            response.headers["x-request-id"] = request_id.get()
            return response
        finally:
            request_id.reset(token)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/metrics")
    async def metrics():
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return app
