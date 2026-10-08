"""Fault injection and recovery, with the ground truth stored in Postgres.

An injection:
  0. regenerates the company repo from scratch (clean history, dates relative to now);
  1. commits the culprit change to the company repo (if the scenario has one),
     mixed in with decoy commits (see timeline.py);
  2. turns on the switches of the affected services in Redis (`faults:{service}`)
     and, for infrastructure faults, stops containers or leaves a Postgres session
     stuck holding a lock;
  3. stores the correct answer in the `groundtruth` database.

Recovery does the reverse: turns the switches off, starts the containers again,
terminates the stuck session and reverts the commit.
There is at most one active injection at a time, so that each incident has a
single root cause.
"""

import asyncio
import json
import random
import re
import socket
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import asyncpg
import docker
from redis.asyncio import Redis

from incilot_sim.company_repo import build, revert
from incilot_sim.injector import scenarios, timeline
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
ALTER TABLE injections ADD COLUMN IF NOT EXISTS resolved_by TEXT;
"""
# Who performs the rollback in the company repo: the on-call engineer.
ON_CALL = "SRE On-call <sre@shop.example>"


class InjectionError(Exception):
    pass


def with_database(url: str, database: str) -> str:
    return urlunsplit(urlsplit(url)._replace(path=f"/{database}"))


async def connect_groundtruth(url: str) -> asyncpg.Pool:
    """Opens the ground-truth database, creating it if it does not exist yet."""
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
    """Leaves a Postgres session that takes a lock and never finishes (a stuck migration).

    The connection is dropped without cancelling the query: Postgres does not notice
    the client has gone while the query runs, so the session keeps holding the lock.
    """
    conn = await asyncpg.connect(
        with_database(postgres_url, session["database"]),
        server_settings={"application_name": session["application_name"]},
    )
    query = asyncio.ensure_future(conn.execute(session["sql"]))
    await asyncio.sleep(1)  # give it time to take the lock
    if query.done():
        query.result()  # the SQL failed: surface it
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
    """Containers of those services in the same compose project as the injector."""
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
    def __init__(self, db: asyncpg.Pool, redis: Redis, data: Path, repo: Path, postgres_url: str):
        self.db = db
        self.data = data  # incilot-data
        self.redis = redis
        self.repo = repo
        self.postgres_url = postgres_url  # any database on the company's server
        self._docker: docker.DockerClient | None = None

    @property
    def docker(self) -> docker.DockerClient:
        # Only connects if a scenario touches containers.
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
            raise InjectionError(f"there is already an active injection: {current['id']}")
        now = datetime.now(UTC)
        build(self.data, self.repo, now)
        decoys = timeline.load_decoys(self.data, scenarios.authors(self.data))
        steps = timeline.plan(self.repo, variant.culprit, decoys, now, random.Random())
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

    async def recover(self, resolved_by: str = "manual") -> dict:
        current = await self.active()
        if current is None:
            raise InjectionError("there is no active injection")
        if stopped := current["infra"].get("stop"):
            for container in compose_containers(self.docker, stopped):
                container.start()
        if session := current["infra"].get("stuck_session"):
            await end_stuck_session(self.postgres_url, session)
        # A real rollback redeploys the service: e.g. leaked memory is only returned
        # to the operating system by restarting the process.
        if restart := current["infra"].get("restart_on_recover"):
            for container in compose_containers(self.docker, restart):
                container.restart()
        await clear_faults(self.redis, list(current["faults"]))
        if current["culprit_sha"]:
            revert(self.repo, current["culprit_sha"], ON_CALL, datetime.now(UTC))
        row = await self.db.fetchrow(
            "UPDATE injections SET recovered_at = now(), resolved_by = $2 "
            "WHERE id = $1 RETURNING *",
            current["id"],
            resolved_by,
        )
        return _decode(row)

    async def execute_action(self, kind: str, target: str) -> dict:
        """Executes an approved action on the mini-company (the simulation connector).

        If it is the correct action for the active incident, it resolves it. If not, it
        applies the literal effect (revert *that* commit, restart *that* service) and the
        incident continues. The response is the same either way: it does not tell the
        agent whether it got it right.
        """
        current = await self.active()
        if current and resolves(current, kind, target):
            await self.recover(resolved_by="agent")
            return {"status": "executed", "detail": EXECUTED[kind].format(target=target)}
        try:
            await self._literal_effect(kind, target)
        except Exception as exc:
            return {"status": "failed", "detail": f"{type(exc).__name__}: {exc}"[:300]}
        return {"status": "executed", "detail": EXECUTED[kind].format(target=target)}

    async def _literal_effect(self, kind: str, target: str) -> None:
        if kind in ("rollback", "revert_config"):
            if not SHA.match(target):
                raise ValueError(f"invalid commit: {target}")
            revert(self.repo, target, ON_CALL, datetime.now(UTC))
        elif kind == "restart":
            if target not in COMPANY_SERVICES:
                raise ValueError(f"cannot restart {target}: only {', '.join(COMPANY_SERVICES)}")
            containers = compose_containers(self.docker, [target])
            if not containers:
                raise ValueError(f"unknown service: {target}")
            for container in containers:
                container.restart()
        elif kind == "terminate_session":
            conn = await asyncpg.connect(with_database(self.postgres_url, "postgres"))
            try:
                pids = [int(p) for p in re.findall(r"\d+", target)]
                await conn.fetch(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE (pid = ANY($1::int[]) OR application_name = $2) "
                    "AND datname = ANY($3::text[]) AND pid <> pg_backend_pid()",
                    pids,
                    target,
                    list(COMPANY_SERVICES),
                )
            finally:
                await conn.close()
        elif kind != "escalate":
            raise ValueError(f"unknown action: {kind}")


SHA = re.compile(r"^[0-9a-f]{7,40}$")
# What a wrong (literal) action may touch: the company's services and their databases,
# never the agent, the injector, observability or the shared Postgres and Redis. The
# demo is public, so an amended action comes from a stranger.
COMPANY_SERVICES = ("shop", "users", "inventory", "payments")
EXECUTED = {
    "rollback": "revert of {target} committed and deployed",
    "revert_config": "revert of the {target} config committed and deployed",
    "restart": "{target} restarted",
    "terminate_session": "session {target} terminated",
    "escalate": "escalated to the external owner ({target}); no technical action",
}
REVERTS = {"rollback", "revert_config"}


def resolves(injection: dict, kind: str, target: str) -> bool:
    """Does the action resolve the active incident? (rollback and revert_config are equivalent)."""
    expected = injection["action"]
    if kind != expected and not (kind in REVERTS and expected in REVERTS):
        return False
    target = target.strip().lower()
    if kind in REVERTS:
        culprit = injection["culprit_sha"] or ""
        return len(target) >= 7 and culprit.startswith(target)
    if kind == "restart":
        return injection["service"] in target
    return True  # terminate_session and escalate: the right kind is enough


def _decode(row: asyncpg.Record | None) -> dict | None:
    if row is None:
        return None
    return dict(row) | {"faults": json.loads(row["faults"]), "infra": json.loads(row["infra"])}
