"""Worker: toma investigaciones de la cola, corre el grafo y publica cada paso.

    python -m incilot_agent.worker

Varios workers pueden correr en paralelo: cada trabajo lo toma uno solo (BLPOP).
"""

import asyncio
import json
import logging

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.types import Command
from redis.asyncio import Redis
from redis.exceptions import RedisError

from incilot_agent import config, graph, jobs
from incilot_agent.events import investigation_events
from incilot_agent.executor import NoopExecutor, default_executor
from incilot_agent.llm import dry_run_models, openai_models
from incilot_agent.verification import NullVerifier, PostgresRecorder, PrometheusVerifier

log = logging.getLogger("agent.worker")
BLPOP_SECONDS = 5


async def handle(job: dict, checkpointer, redis: Redis) -> None:
    investigation_id = job["id"]
    meta = jobs.meta_key(investigation_id)
    dry_run = (await redis.hget(meta, "dry_run")) == "1"
    app = graph.build(
        dry_run_models() if dry_run else openai_models(),
        checkpointer,
        executor=NoopExecutor() if dry_run else default_executor(),
        verifier=NullVerifier() if dry_run else PrometheusVerifier(),
        recorder=PostgresRecorder(),
    )
    run_config = {"configurable": {"thread_id": investigation_id}}
    graph_input = (
        {"alert": job["alert"]} if job["kind"] == "start" else Command(resume=job["decision"])
    )

    await redis.hset(meta, "status", "running")
    status = "running"
    try:
        async for event in investigation_events(app, graph_input, run_config):
            await jobs.publish(redis, investigation_id, event)
            if event["type"] == "diagnosis":
                await redis.hset(meta, "diagnosis", json.dumps(event["diagnosis"]))
            elif event["type"] == "awaiting_approval":
                status = "awaiting_approval"
            elif event["type"] == "done":
                status = "done"
    except Exception as exc:
        log.exception("investigación %s falló", investigation_id)
        status = "error"
        await redis.hset(meta, "error", f"{type(exc).__name__}: {exc}"[:500])
        await jobs.publish(redis, investigation_id, {"type": "error", "error": str(exc)[:500]})
    await redis.hset(meta, "status", status)


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    # El timeout de lectura tiene que superar la espera de BLPOP: si no, el cliente corta
    # antes de que Redis conteste "cola vacía".
    redis = Redis.from_url(
        config.AGENT_REDIS_URL, decode_responses=True, socket_timeout=BLPOP_SECONDS + 10
    )
    async with AsyncPostgresSaver.from_conn_string(config.AGENT_STATE_URL) as checkpointer:
        await checkpointer.setup()
        log.info("esperando investigaciones en %s", jobs.QUEUE)
        while True:
            try:
                item = await redis.blpop([jobs.QUEUE], timeout=BLPOP_SECONDS)
            except RedisError as exc:  # Redis reiniciándose: esperar y seguir
                log.warning("redis no disponible (%s); reintento en 2 s", exc)
                await asyncio.sleep(2)
                continue
            if item is None:
                continue
            job = json.loads(item[1])
            log.info("trabajo %s (%s)", job["id"], job["kind"])
            await handle(job, checkpointer, redis)


if __name__ == "__main__":
    asyncio.run(main())
