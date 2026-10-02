"""Servicio de usuarios: perfiles en Postgres con caché en Redis."""

import json
from contextlib import asynccontextmanager

import asyncpg
from fastapi import HTTPException
from redis.asyncio import Redis

from incilot_sim.common.app import create_app
from incilot_sim.common.clients import connect_cache, connect_db
from incilot_sim.common.log import get_logger

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    tier TEXT NOT NULL DEFAULT 'standard',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""
SEED_USERS = 500
CACHE_TTL_SECONDS = 300

log = get_logger(__name__)
db: asyncpg.Pool
cache: Redis


@asynccontextmanager
async def lifespan(_):
    global db, cache
    db = await connect_db(SCHEMA)
    cache = connect_cache()
    if await db.fetchval("SELECT count(*) FROM users") == 0:
        await db.executemany(
            "INSERT INTO users (email, name, tier) VALUES ($1, $2, $3)",
            [
                (f"user{i}@example.com", f"User {i}", "premium" if i % 10 == 0 else "standard")
                for i in range(1, SEED_USERS + 1)
            ],
        )
        log.info("seeded users", count=SEED_USERS)
    yield
    await cache.aclose()
    await db.close()


app = create_app("users", lifespan)


@app.get("/users/{user_id}")
async def get_user(user_id: int):
    key = f"user:{user_id}"
    if cached := await cache.get(key):
        return json.loads(cached)
    row = await db.fetchrow("SELECT id, email, name, tier FROM users WHERE id = $1", user_id)
    if row is None:
        raise HTTPException(404, "user_not_found")
    user = dict(row)
    await cache.set(key, json.dumps(user), ex=CACHE_TTL_SECONDS)
    return user
