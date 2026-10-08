"""Investigation queue and events in Redis. All keys live under `investigation:`.

    investigation:queue            list of jobs (start or decision)
    investigation:{id}             hash: alert, dry_run, status, diagnosis, error
    investigation:{id}:events      stream with the investigation's events

status: queued → running → awaiting_approval → queued → running → done (or error)
"""

import json

from redis.asyncio import Redis

QUEUE = "investigation:queue"
EVENTS_MAXLEN = 2000


def meta_key(investigation_id: str) -> str:
    return f"investigation:{investigation_id}"


def events_key(investigation_id: str) -> str:
    return f"investigation:{investigation_id}:events"


async def enqueue(redis: Redis, job: dict) -> None:
    await redis.hset(meta_key(job["id"]), "status", "queued")
    await redis.rpush(QUEUE, json.dumps(job))


async def publish(redis: Redis, investigation_id: str, event: dict) -> None:
    await redis.xadd(
        events_key(investigation_id),
        {"event": json.dumps(event, ensure_ascii=False, default=str)},
        maxlen=EVENTS_MAXLEN,
        approximate=True,
    )
