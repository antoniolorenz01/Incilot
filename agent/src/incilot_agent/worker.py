"""Worker: takes investigations off the queue, runs the graph and publishes each step.

    python -m incilot_agent.worker

Several workers can run in parallel: each job is taken by only one of them (BLPOP).
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
from incilot_agent.llm import agent_models, dry_run_models
from incilot_agent.verification import NullVerifier, PostgresRecorder, PrometheusVerifier

log = logging.getLogger("agent.worker")
BLPOP_SECONDS = 5


async def handle(job: dict, checkpointer, redis: Redis) -> None:
    investigation_id = job["id"]
    meta = jobs.meta_key(investigation_id)
    dry_run = (await redis.hget(meta, "dry_run")) == "1"
    app = graph.build(
        dry_run_models() if dry_run else agent_models(),
        checkpointer,
        executor=NoopExecutor() if dry_run else default_executor(),
        verifier=NullVerifier() if dry_run else PrometheusVerifier(),
        recorder=PostgresRecorder(),
    )
    run_config = {"configurable": {"thread_id": investigation_id}}
    graph_input = (
        {"alert": job["alert"], "since": job.get("since")}
        if job["kind"] == "start"
        else Command(resume=job["decision"])
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
        log.exception("investigation %s failed", investigation_id)
        status = "error"
        await redis.hset(meta, "error", f"{type(exc).__name__}: {exc}"[:500])
        await jobs.publish(redis, investigation_id, {"type": "error", "error": str(exc)[:500]})
    await redis.hset(meta, "status", status)


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    # The read timeout must exceed the BLPOP wait: otherwise the client gives up before
    # Redis answers "queue empty".
    redis = Redis.from_url(
        config.AGENT_REDIS_URL, decode_responses=True, socket_timeout=BLPOP_SECONDS + 10
    )
    async with AsyncPostgresSaver.from_conn_string(config.AGENT_STATE_URL) as checkpointer:
        await checkpointer.setup()
        log.info("waiting for investigations on %s", jobs.QUEUE)
        while True:
            try:
                item = await redis.blpop([jobs.QUEUE], timeout=BLPOP_SECONDS)
            except RedisError as exc:  # Redis restarting: wait and carry on
                log.warning("redis unavailable (%s); retrying in 2 s", exc)
                await asyncio.sleep(2)
                continue
            if item is None:
                continue
            job = json.loads(item[1])
            log.info("job %s (%s)", job["id"], job["kind"])
            await handle(job, checkpointer, redis)


if __name__ == "__main__":
    asyncio.run(main())
