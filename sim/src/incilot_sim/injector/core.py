"""Inyección y recuperación de fallos, con el ground truth guardado en Postgres.

Una inyección:
  1. commitea el cambio culpable en el repo de la empresa (si el escenario lo tiene);
  2. activa los interruptores de los servicios afectados en Redis (`faults:{service}`)
     y, en fallos de infraestructura, para contenedores;
  3. guarda la respuesta correcta en la base `groundtruth`.

La recuperación hace lo inverso: apaga los interruptores, vuelve a arrancar los
contenedores y revierte el commit.
Hay como mucho una inyección activa a la vez, para que cada incidente tenga una
única causa raíz.
"""

import json
import socket
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import asyncpg
import docker
from redis.asyncio import Redis

from incilot_sim.company_repo import apply_edit, commit, revert
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
    faults JSONB NOT NULL,
    infra JSONB NOT NULL DEFAULT '{}',
    injected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    recovered_at TIMESTAMPTZ
);
ALTER TABLE injections ADD COLUMN IF NOT EXISTS infra JSONB NOT NULL DEFAULT '{}';
"""
# Quien hace el rollback en el repo de la empresa: la guardia de turno.
ON_CALL = "Guardia SRE <sre@tienda.example>"


class InjectionError(Exception):
    pass


async def connect_groundtruth(url: str) -> asyncpg.Pool:
    """Abre la base de ground truth, creándola si todavía no existe."""
    try:
        pool = await asyncpg.create_pool(url, min_size=1, max_size=2)
    except asyncpg.InvalidCatalogNameError:
        parts = urlsplit(url)
        admin = await asyncpg.connect(urlunsplit(parts._replace(path="/postgres")))
        try:
            await admin.execute(f'CREATE DATABASE "{parts.path.lstrip("/")}"')
        finally:
            await admin.close()
        pool = await asyncpg.create_pool(url, min_size=1, max_size=2)
    await pool.execute(SCHEMA)
    return pool


def commit_culprit(repo: Path, culprit: dict, now: datetime) -> str:
    for edit in culprit["edits"]:
        apply_edit(repo / edit["file"], edit["old"], edit["new"])
    when = now - timedelta(minutes=culprit["minutes_ago"])
    return commit(repo, culprit["author"], culprit["message"], when)


async def activate_faults(redis: Redis, faults: dict[str, dict]) -> None:
    for service, switches in faults.items():
        key = f"faults:{service}"
        await redis.delete(key)
        await redis.hset(key, mapping={name: json.dumps(value) for name, value in switches.items()})


async def clear_faults(redis: Redis, services: list[str]) -> None:
    if services:
        await redis.delete(*(f"faults:{service}" for service in services))


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
    def __init__(self, db: asyncpg.Pool, redis: Redis, repo: Path):
        self.db = db
        self.redis = redis
        self.repo = repo
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

    async def inject(self, variant: Variant) -> dict:
        if current := await self.active():
            raise InjectionError(f"ya hay una inyección activa: {current['id']}")
        now = datetime.now(UTC)
        sha = commit_culprit(self.repo, variant.culprit, now) if variant.culprit else None
        await activate_faults(self.redis, variant.faults)
        if stop := variant.infra.get("stop"):
            for container in compose_containers(self.docker, stop):
                container.stop()
        row = await self.db.fetchrow(
            "INSERT INTO injections "
            "(scenario, variant, category, service, root_cause, action, culprit_sha, "
            "faults, infra) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9) RETURNING *",
            variant.scenario,
            variant.id,
            variant.category,
            variant.service,
            variant.ground_truth["root_cause"],
            variant.ground_truth["action"],
            sha,
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
