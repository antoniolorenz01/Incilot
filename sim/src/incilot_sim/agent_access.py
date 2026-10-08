"""The agent's access to Postgres and Redis: read-only and unable to reach the answer.

The agent connects as `agent`:
  - Postgres: read access to the services' databases and the activity views
    (pg_stat_activity, pg_locks); no access to `groundtruth`. It owns its own
    database, `agent_state`, where it stores the checkpoints of its investigations.
  - Redis: read access to the caches (`user:*`, `catalog`) and read/write access to its
    queue and events (`investigation:*`, db 3); no access to `faults:*` (the
    switches), no listing keys or flushing databases. The user is defined in compose.yaml.

    python -m incilot_sim.agent_access    # checks the access rules (make agent-access)
"""

import asyncio
import os
import sys
from urllib.parse import urlsplit, urlunsplit

import asyncpg
from redis.asyncio import Redis
from redis.exceptions import NoPermissionError

AGENT_USER = "agent"
AGENT_PASSWORD = os.getenv("AGENT_PASSWORD", "agent")
SERVICE_DATABASES = ["users", "inventory", "payments", "shop"]
FORBIDDEN_DATABASES = ["groundtruth"]
STATE_DATABASE = "agent_state"


def _url(admin_url: str, database: str, user: str | None = None) -> str:
    parts = urlsplit(admin_url)
    if user:
        parts = parts._replace(netloc=f"{user}:{AGENT_PASSWORD}@{parts.hostname}:{parts.port}")
    return urlunsplit(parts._replace(path=f"/{database}"))


async def ensure_postgres_access(admin_url: str) -> None:
    """Creates or updates the `agent` role (idempotent). Called by the injector on startup."""
    conn = await asyncpg.connect(_url(admin_url, "postgres"))
    try:
        if not await conn.fetchval("SELECT 1 FROM pg_roles WHERE rolname = $1", AGENT_USER):
            await conn.execute(f"CREATE ROLE {AGENT_USER} LOGIN PASSWORD '{AGENT_PASSWORD}'")
        await conn.execute(f"GRANT pg_read_all_stats TO {AGENT_USER}")
        if not await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", STATE_DATABASE):
            await conn.execute(f"CREATE DATABASE {STATE_DATABASE} OWNER {AGENT_USER}")
    finally:
        await conn.close()
    # pgvector for the agent's RAG: creating the extension requires admin rights.
    conn = await asyncpg.connect(_url(admin_url, STATE_DATABASE))
    try:
        await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        for db in FORBIDDEN_DATABASES:
            await conn.execute(f"REVOKE ALL ON DATABASE {db} FROM PUBLIC, {AGENT_USER}")
    finally:
        await conn.close()
    for db in SERVICE_DATABASES:
        conn = await asyncpg.connect(_url(admin_url, db))
        try:
            await conn.execute(f"GRANT CONNECT ON DATABASE {db} TO {AGENT_USER}")
            await conn.execute(f"GRANT USAGE ON SCHEMA public TO {AGENT_USER}")
            await conn.execute(f"GRANT SELECT ON ALL TABLES IN SCHEMA public TO {AGENT_USER}")
            await conn.execute(
                f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO {AGENT_USER}"
            )
        finally:
            await conn.close()


async def _expect(label: str, allowed: bool, check) -> bool:
    try:
        await check()
        got = True
    except (asyncpg.PostgresError, NoPermissionError, OSError):
        got = False
    ok = got == allowed
    expected = "allowed" if allowed else "denied"
    print(f"{'OK   ' if ok else 'FAIL '} {label:52} {expected}", flush=True)
    return ok


async def check(admin_url: str, redis_host: str) -> bool:
    async def pg(database: str, sql: str):
        conn = await asyncpg.connect(_url(admin_url, database, AGENT_USER))
        try:
            await conn.fetch(sql)
        finally:
            await conn.close()

    def redis(db: int) -> Redis:
        return Redis(host=redis_host, db=db, username=AGENT_USER, password=AGENT_PASSWORD)

    async def redis_call(db: int, *command):
        client = redis(db)
        try:
            await client.execute_command(*command)
        finally:
            await client.aclose()

    checks = [
        ("Postgres: read a service's tables", True, lambda: pg("users", "SELECT 1 FROM users")),
        (
            "Postgres: see other sessions' activity",
            True,
            lambda: pg("inventory", "SELECT query FROM pg_stat_activity"),
        ),
        (
            "Postgres: write to a service",
            False,
            lambda: pg("users", "UPDATE users SET name = name WHERE id = 0"),
        ),
        ("Postgres: connect to groundtruth", False, lambda: pg("groundtruth", "SELECT 1")),
        (
            "Postgres: write to its own database (agent_state)",
            True,
            lambda: pg("agent_state", "CREATE TABLE IF NOT EXISTS access_probe (x int)"),
        ),
        ("Redis: read the users cache (db 0)", True, lambda: redis_call(0, "GET", "user:1")),
        ("Redis: read the shop cache (db 1)", True, lambda: redis_call(1, "GET", "catalog")),
        (
            "Redis: read switches (db 2, faults:*)",
            False,
            lambda: redis_call(2, "HGETALL", "faults:shop"),
        ),
        ("Redis: list keys", False, lambda: redis_call(0, "SCAN", "0")),
        ("Redis: write to the cache", False, lambda: redis_call(0, "SET", "user:1", "x")),
        (
            "Redis: write to its queue (investigation:*)",
            True,
            lambda: redis_call(3, "SET", "investigation:access-probe", "x", "EX", "60"),
        ),
        ("Redis: flush a database (FLUSHDB)", False, lambda: redis_call(3, "FLUSHDB")),
    ]
    results = [await _expect(label, allowed, fn) for label, allowed, fn in checks]
    print(f"\n{sum(results)}/{len(results)} access checks as expected")
    return all(results)


if __name__ == "__main__":
    ok = asyncio.run(
        check(os.environ["GROUNDTRUTH_DATABASE_URL"], os.getenv("REDIS_HOST", "redis"))
    )
    sys.exit(0 if ok else 1)
