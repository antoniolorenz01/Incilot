"""Fault switches that the injector flips at runtime.

Each service reads the Redis hash `faults:{service}` every few seconds. If Redis
does not respond, it keeps the last state, so a fault survives a Redis outage
caused by another fault.

Faults do not give themselves away: they write no logs of their own and their
symptoms look just like a real problem. /health and /metrics are never affected.

Hash fields (each value is JSON):

    latency             {"ms": 800, "jitter_ms": 200, "paths": ["/reservations"]}
    errors              {"rate": 0.2, "traceback": "Traceback ...", "paths": [...]}
    rate_limit          {"rps": 5}
    memory_leak         {"kb_per_request": 256}
    db_connection_leak  {"connections": 9}
    flags               ["skip_reservation_release"]
    overrides           {"decline_rate": 0.5}

`paths` is optional: path prefixes the fault is limited to.
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
    """Simulated 500 error. The middleware logs `traceback` as if it were real."""

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
    """State of the faults active in this process, and their effects."""

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
        """Global FastAPI dependency: runs on every request, after routing."""
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
                return  # pool exhausted by traffic: retried on the next cycle

    async def release_all(self) -> None:
        self.apply(Faults())
        await self.sync_connection_leak()


switchboard = Switchboard()


def flag(name: str) -> bool:
    """Hook in a service's code: `if faults.flag("skip_reservation_release")`."""
    return name in switchboard.faults.flags


def override(key: str, default):
    """Config that a fault can override: `faults.override("decline_rate", DECLINE_RATE)`."""
    return switchboard.faults.overrides.get(key, default)


def _applies(fault: dict, path: str) -> bool:
    paths = fault.get("paths")
    return not paths or any(path.startswith(p) for p in paths)


async def _poll(redis: Redis, key: str) -> None:
    while True:
        # Redis down or invalid data: the last known state is kept.
        with suppress(Exception):
            switchboard.apply(Faults.parse(await redis.hgetall(key)))
        with suppress(Exception):
            await switchboard.sync_connection_leak()
        await asyncio.sleep(POLL_INTERVAL_SECONDS)


@asynccontextmanager
async def control(service: str):
    """Keeps `switchboard` in sync with Redis while the service runs."""
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
