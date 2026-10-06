"""Inyección y recuperación de fallos, con el ground truth guardado en Postgres.

Una inyección:
  1. commitea el cambio culpable en el repo de la empresa (si el escenario lo tiene),
     mezclado con commits señuelo (ver timeline.py);
  2. activa los interruptores de los servicios afectados en Redis (`faults:{service}`)
     y, en fallos de infraestructura, para contenedores o deja una sesión de
     Postgres trabada con un lock;
  3. guarda la respuesta correcta en la base `groundtruth`.

La recuperación hace lo inverso: apaga los interruptores, vuelve a arrancar los
contenedores, termina la sesión trabada y revierte el commit.
Hay como mucho una inyección activa a la vez, para que cada incidente tenga una
única causa raíz.
"""

import asyncio
import json
import random
import socket
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import asyncpg
import docker
from redis.asyncio import Redis

from incilot_sim.company_repo import revert
from incilot_sim.injector import timeline
from incilot_sim.injector.scenarios import Variant

SCHEMA = """
CREATE TABLE IF NOT EXISTS injections (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scenario TEXT NOT NULL,
    variant TEXT NOT NULL,
    category TEXT NOT NULL,
    service TEXT NOT NULL,
    root_cause TEXT NOT NULL,
    action TEXT NOT NULL,
    culprit_sha TEXT,
    decoy_shas TEXT[] NOT NULL DEFAULT '{}',
    faults JSONB NOT NULL,
    infra JSONB NOT NULL DEFAULT '{}',
    injected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    recovered_at TIMESTAMPTZ
);
ALTER TABLE injections ADD COLUMN IF NOT EXISTS infra JSONB NOT NULL DEFAULT '{}';
ALTER TABLE injections ADD COLUMN IF NOT EXISTS decoy_shas TEXT[] NOT NULL DEFAULT '{}';
"""
# Quien hace el rollback en el repo de la empresa: la guardia de turno.
ON_CALL = "Guardia SRE <sre@tienda.example>"


class InjectionError(Exception):
    pass


def with_database(url: str, database: str) -> str:
    return urlunsplit(urlsplit(url)._replace(path=f"/{database}"))


async def connect_groundtruth(url: str) -> asyncpg.Pool:
    """Abre la base de ground truth, creándola si todavía no existe."""
    try:
        pool = await asyncpg.create_pool(url, min_size=1, max_size=2)
    except asyncpg.InvalidCatalogNameError:
        admin = await asyncpg.connect(with_database(url, "postgres"))
        try:
            await admin.execute(f'CREATE DATABASE "{urlsplit(url).path.lstrip("/")}"')
        finally:
            await admin.close()
        pool = await asyncpg.create_pool(url, min_size=1, max_size=2)
    await pool.execute(SCHEMA)
    return pool


async def activate_faults(redis: Redis, faults: dict[str, dict]) -> None:
    for service, switches in faults.items():
        key = f"faults:{service}"
        await redis.delete(key)
        await redis.hset(key, mapping={name: json.dumps(value) for name, value in switches.items()})


async def clear_faults(redis: Redis, services: list[str]) -> None:
    if services:
        await redis.delete(*(f"faults:{service}" for service in services))


async def start_stuck_session(postgres_url: str, session: dict) -> None:
    """Deja en Postgres una sesión que toma un lock y no termina (una migración trabada).

    Se suelta la conexión sin cancelar la consulta: Postgres no se entera de que el
    cliente se fue mientras la consulta corre, así que la sesión sigue con el lock.
    """
    conn = await asyncpg.connect(
        with_database(postgres_url, session["database"]),
        server_settings={"application_name": session["application_name"]},
    )
    query = asyncio.ensure_future(conn.execute(session["sql"]))
    await asyncio.sleep(1)  # que llegue a tomar el lock
    if query.done():
        query.result()  # el SQL falló: que se vea
    query.add_done_callback(lambda q: q.cancelled() or q.exception())
    conn.terminate()


async def end_stuck_session(postgres_url: str, session: dict) -> None:
    conn = await asyncpg.connect(with_database(postgres_url, "postgres"))
    try:
        await conn.fetch(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE application_name = $1",
            session["application_name"],
        )
    finally:
        await conn.close()


def compose_containers(client: docker.DockerClient, services: list[str]) -> list:
    """Contenedores de esos servicios en el mismo proyecto de compose que el injector."""
    project = client.containers.get(socket.gethostname()).labels["com.docker.compose.project"]
    return [
        container
        for service in services
        for container in client.containers.list(
            all=True,
            filters={
                "label": [
                    f"com.docker.compose.project={project}",
                    f"com.docker.compose.service={service}",
                ]
            },
        )
    ]


class Injector:
    def __init__(self, db: asyncpg.Pool, redis: Redis, repo: Path, postgres_url: str):
        self.db = db
        self.redis = redis
        self.repo = repo
        self.postgres_url = postgres_url  # cualquier base del servidor de la empresa
        self._docker: docker.DockerClient | None = None

    @property
    def docker(self) -> docker.DockerClient:
        # Solo se conecta si un escenario toca contenedores.
        if self._docker is None:
            self._docker = docker.from_env()
        return self._docker

    async def aclose(self) -> None:
        await self.redis.aclose()
        await self.db.close()

    async def active(self) -> dict | None:
        row = await self.db.fetchrow(
            "SELECT * FROM injections WHERE recovered_at IS NULL ORDER BY injected_at DESC LIMIT 1"
        )
        return _decode(row)

    async def history(self, limit: int = 20) -> list[dict]:
        rows = await self.db.fetch(
            "SELECT * FROM injections ORDER BY injected_at DESC LIMIT $1", limit
        )
        return [_decode(r) for r in rows]

    async def inject(self, variant: Variant, decoys: list[dict] = ()) -> dict:
        if current := await self.active():
            raise InjectionError(f"ya hay una inyección activa: {current['id']}")
        steps = timeline.plan(
            self.repo, variant.culprit, list(decoys), datetime.now(UTC), random.Random()
        )
        sha, decoy_shas = None, []
        for step in steps:
            step_sha = timeline.apply(self.repo, step)
            if step.culprit:
                sha = step_sha
            else:
                decoy_shas.append(step_sha)
        await activate_faults(self.redis, variant.faults)
        if stop := variant.infra.get("stop"):
            for container in compose_containers(self.docker, stop):
                container.stop()
        if session := variant.infra.get("stuck_session"):
            await start_stuck_session(self.postgres_url, session)
        row = await self.db.fetchrow(
            "INSERT INTO injections "
            "(scenario, variant, category, service, root_cause, action, culprit_sha, "
            "decoy_shas, faults, infra) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10) RETURNING *",
            variant.scenario,
            variant.id,
            variant.category,
            variant.service,
            variant.ground_truth["root_cause"],
            variant.ground_truth["action"],
            sha,
            decoy_shas,
            json.dumps(variant.faults),
            json.dumps(variant.infra),
        )
        return _decode(row)

    async def recover(self) -> dict:
        current = await self.active()
        if current is None:
            raise InjectionError("no hay ninguna inyección activa")
        if stopped := current["infra"].get("stop"):
            for container in compose_containers(self.docker, stopped):
                container.start()
        if session := current["infra"].get("stuck_session"):
            await end_stuck_session(self.postgres_url, session)
        # Un rollback real redeploya el servicio: p. ej. la memoria de un leak solo
        # vuelve al sistema operativo reiniciando el proceso.
        if restart := current["infra"].get("restart_on_recover"):
            for container in compose_containers(self.docker, restart):
                container.restart()
        await clear_faults(self.redis, list(current["faults"]))
        if current["culprit_sha"]:
            revert(self.repo, current["culprit_sha"], ON_CALL, datetime.now(UTC))
        row = await self.db.fetchrow(
            "UPDATE injections SET recovered_at = now() WHERE id = $1 RETURNING *", current["id"]
        )
        return _decode(row)


def _decode(row: asyncpg.Record | None) -> dict | None:
    if row is None:
        return None
    return dict(row) | {"faults": json.loads(row["faults"]), "infra": json.loads(row["infra"])}
