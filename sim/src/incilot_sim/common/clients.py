"""Connections to Postgres, Redis and other services, configured via environment variables."""

import os
import time
from uuid import uuid4

import asyncpg
import httpx
from redis.asyncio import Redis

from incilot_sim.common import faults
from incilot_sim.common.faults import switchboard
from incilot_sim.common.log import request_id
from incilot_sim.common.metrics import UPSTREAM_LATENCY, UPSTREAM_REQUESTS


async def connect_db(schema: str) -> asyncpg.Pool:
    """Opens the `DATABASE_URL` pool and applies the schema (idempotent)."""
    pool = await asyncpg.create_pool(
        os.environ["DATABASE_URL"], min_size=1, max_size=int(os.getenv("DB_POOL_SIZE", "10"))
    )
    await pool.execute(schema)
    switchboard.track_pool(pool)
    return pool


def connect_cache() -> Redis:
    return Redis.from_url(os.environ["REDIS_URL"], decode_responses=True)


class Upstream:
    """HTTP client for another service: propagates request_id, measures latency and errors."""

    def __init__(self, name: str, base_url: str, timeout: float = 2.0):
        self.name = name
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout)

    async def request(self, method: str, path: str, **kwargs) -> httpx.Response:
        headers = {"x-request-id": request_id.get() or uuid4().hex}
        status = "error"
        start = time.perf_counter()
        try:
            # A fault can simulate a misconfigured URL (e.g. `inventory_url`).
            url = faults.override(f"{self.name}_url", "") + path
            response = await self._client.request(method, url, headers=headers, **kwargs)
            status = str(response.status_code)
            return response
        except httpx.TimeoutException:
            status = "timeout"
            raise
        finally:
            UPSTREAM_REQUESTS.labels(self.name, status).inc()
            UPSTREAM_LATENCY.labels(self.name).observe(time.perf_counter() - start)

    async def aclose(self) -> None:
        await self._client.aclose()
