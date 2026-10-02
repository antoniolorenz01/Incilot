"""Interruptores de fallos que el injector activa en caliente.

Cada servicio lee el hash de Redis `faults:{service}` cada pocos segundos. Si Redis
no responde, conserva el último estado: así un fallo sobrevive a una caída de Redis
provocada por otro fallo.

Los fallos no se delatan: no escriben logs propios y sus síntomas tienen la misma
forma que un problema real. /health y /metrics nunca se ven afectados.

Campos del hash (cada valor es JSON):

    latency             {"ms": 800, "jitter_ms": 200, "paths": ["/reservations"]}
    errors              {"rate": 0.2, "traceback": "Traceback ...", "paths": [...]}
    rate_limit          {"rps": 5}
    memory_leak         {"kb_per_request": 256}
    db_connection_leak  {"connections": 9}
    flags               ["skip_reservation_release"]
    overrides           {"decline_rate": 0.5}

`paths` es opcional: prefijos de ruta a los que se limita el fallo.
"""

import asyncio
import json
import os
import random
import time
from collections import deque
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field, fields

import asyncpg
from fastapi import HTTPException, Request
from redis.asyncio import Redis

POLL_INTERVAL_SECONDS = 2
UNAFFECTED_PATHS = {"/health", "/metrics"}


class InjectedError(Exception):
    """Error 500 simulado. El middleware loguea `traceback` como si fuera real."""

    def __init__(self, traceback: str):
        super().__init__(traceback)
        self.traceback = traceback


@dataclass(frozen=True)
class Faults:
    latency: dict | None = None
    errors: dict | None = None
    rate_limit: dict | None = None
    memory_leak: dict | None = None
    db_connection_leak: dict | None = None
    flags: frozenset[str] = frozenset()
    overrides: dict = field(default_factory=dict)

    @classmethod
    def parse(cls, raw: dict[str, str]) -> "Faults":
        known = {f.name for f in fields(cls)}
        values = {k: json.loads(v) for k, v in raw.items() if k in known}
        if "flags" in values:
            values["flags"] = frozenset(values["flags"])
        return cls(**values)


class Switchboard:
    """Estado de los fallos activos en este proceso y sus efectos."""

    def __init__(self):
        self.faults = Faults()
        self._pool: asyncpg.Pool | None = None
        self._held_connections: list = []
        self._leaked_memory: list[bytearray] = []
        self._recent_requests: deque[float] = deque()

    def apply(self, faults: Faults) -> None:
        if not faults.memory_leak:
            self._leaked_memory.clear()
        self.faults = faults

    def track_pool(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def disrupt(self, request: Request) -> None:
        """Dependencia global de FastAPI: corre en cada request, después del ruteo."""
        path = request.url.path
        if path in UNAFFECTED_PATHS:
            return
        faults = self.faults
        if faults.rate_limit and not self._within_rate_limit(faults.rate_limit["rps"]):
            raise HTTPException(429, "rate_limited")
        if faults.memory_leak:
            self._leaked_memory.append(bytearray(faults.memory_leak["kb_per_request"] * 1024))
        if faults.latency and _applies(faults.latency, path):
            jitter = faults.latency.get("jitter_ms", 0)
            delay_ms = faults.latency["ms"] + random.uniform(-jitter, jitter)
            await asyncio.sleep(max(delay_ms, 0) / 1000)
        if (
            faults.errors
            and _applies(faults.errors, path)
            and random.random() < faults.errors["rate"]
        ):
            raise InjectedError(faults.errors["traceback"])

    def _within_rate_limit(self, rps: float) -> bool:
        now = time.monotonic()
        while self._recent_requests and now - self._recent_requests[0] > 1:
            self._recent_requests.popleft()
        if len(self._recent_requests) >= rps:
            return False
        self._recent_requests.append(now)
        return True

    async def sync_connection_leak(self) -> None:
        if self._pool is None:
            return
        wanted = (self.faults.db_connection_leak or {}).get("connections", 0)
        while len(self._held_connections) > wanted:
            await self._pool.release(self._held_connections.pop())
        while len(self._held_connections) < wanted:
            try:
                self._held_connections.append(await self._pool.acquire(timeout=1))
            except TimeoutError:
                return  # pool agotado por el tráfico: se reintenta en el próximo ciclo

    async def release_all(self) -> None:
        self.apply(Faults())
        await self.sync_connection_leak()


switchboard = Switchboard()


def flag(name: str) -> bool:
    """Hook en el código de un servicio: `if faults.flag("skip_reservation_release")`."""
    return name in switchboard.faults.flags


def override(key: str, default):
    """Config que un fallo puede pisar: `faults.override("decline_rate", DECLINE_RATE)`."""
    return switchboard.faults.overrides.get(key, default)


def _applies(fault: dict, path: str) -> bool:
    paths = fault.get("paths")
    return not paths or any(path.startswith(p) for p in paths)


async def _poll(redis: Redis, key: str) -> None:
    while True:
        # Redis caído o datos inválidos: se mantiene el último estado conocido.
        with suppress(Exception):
            switchboard.apply(Faults.parse(await redis.hgetall(key)))
        with suppress(Exception):
            await switchboard.sync_connection_leak()
        await asyncio.sleep(POLL_INTERVAL_SECONDS)


@asynccontextmanager
async def control(service: str):
    """Mantiene `switchboard` sincronizado con Redis mientras corre el servicio."""
    url = os.getenv("FAULTS_REDIS_URL")
    if not url:
        yield
        return
    redis = Redis.from_url(url, decode_responses=True, socket_timeout=1, socket_connect_timeout=1)
    poller = asyncio.create_task(_poll(redis, f"faults:{service}"))
    try:
        yield
    finally:
        poller.cancel()
        with suppress(asyncio.CancelledError):
            await poller
        await switchboard.release_all()
        await redis.aclose()
