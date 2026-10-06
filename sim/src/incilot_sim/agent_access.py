"""Accesos del agente a Postgres y Redis: solo lectura y sin llegar a la respuesta.

El agente se conecta como `agent`:
  - Postgres: lectura sobre las bases de los servicios y las vistas de actividad
    (pg_stat_activity, pg_locks); sin acceso a `groundtruth`. Es dueño de su propia
    base, `agent_state`, donde guarda los checkpoints de sus investigaciones.
  - Redis: lectura de las cachés (`user:*`, `catalog`) y lectura y escritura de su
    cola y sus eventos (`investigation:*`, db 3); sin acceso a `faults:*` (los
    interruptores), sin listar claves ni borrar bases. El usuario se define en compose.yaml.

    python -m incilot_sim.agent_access    # verifica los accesos (make agent-access)
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
    """Crea o actualiza el rol `agent` (idempotente). Lo llama el injector al arrancar."""
    conn = await asyncpg.connect(_url(admin_url, "postgres"))
    try:
        if not await conn.fetchval("SELECT 1 FROM pg_roles WHERE rolname = $1", AGENT_USER):
            await conn.execute(f"CREATE ROLE {AGENT_USER} LOGIN PASSWORD '{AGENT_PASSWORD}'")
        await conn.execute(f"GRANT pg_read_all_stats TO {AGENT_USER}")
        if not await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", STATE_DATABASE):
            await conn.execute(f"CREATE DATABASE {STATE_DATABASE} OWNER {AGENT_USER}")
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
    expected = "permitido" if allowed else "denegado"
    print(f"{'OK   ' if ok else 'FALLA'} {label:52} {expected}", flush=True)
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
        ("Postgres: leer tablas de un servicio", True, lambda: pg("users", "SELECT 1 FROM users")),
        (
            "Postgres: ver la actividad de otras sesiones",
            True,
            lambda: pg("inventory", "SELECT query FROM pg_stat_activity"),
        ),
        (
            "Postgres: escribir en un servicio",
            False,
            lambda: pg("users", "UPDATE users SET name = name WHERE id = 0"),
        ),
        ("Postgres: conectarse a groundtruth", False, lambda: pg("groundtruth", "SELECT 1")),
        (
            "Postgres: escribir en su base (agent_state)",
            True,
            lambda: pg("agent_state", "CREATE TABLE IF NOT EXISTS access_probe (x int)"),
        ),
        ("Redis: leer la caché de users (db 0)", True, lambda: redis_call(0, "GET", "user:1")),
        ("Redis: leer la caché de shop (db 1)", True, lambda: redis_call(1, "GET", "catalog")),
        (
            "Redis: leer interruptores (db 2, faults:*)",
            False,
            lambda: redis_call(2, "HGETALL", "faults:shop"),
        ),
        ("Redis: listar claves", False, lambda: redis_call(0, "SCAN", "0")),
        ("Redis: escribir en la caché", False, lambda: redis_call(0, "SET", "user:1", "x")),
        (
            "Redis: escribir en su cola (investigation:*)",
            True,
            lambda: redis_call(3, "SET", "investigation:access-probe", "x", "EX", "60"),
        ),
        ("Redis: borrar una base (FLUSHDB)", False, lambda: redis_call(3, "FLUSHDB")),
    ]
    results = [await _expect(label, allowed, fn) for label, allowed, fn in checks]
    print(f"\n{sum(results)}/{len(results)} accesos como se espera")
    return all(results)


if __name__ == "__main__":
    ok = asyncio.run(
        check(os.environ["GROUNDTRUTH_DATABASE_URL"], os.getenv("REDIS_HOST", "redis"))
    )
    sys.exit(0 if ok else 1)
