"""Traffic generator: virtual users who browse and buy in the shop non-stop."""

import asyncio
import os
import random
from collections import Counter

import httpx

from incilot_sim.common.log import configure_logging, get_logger

SHOP_URL = os.getenv("SHOP_URL", "http://shop:8000")
SHOPPERS = int(os.getenv("TRAFFIC_SHOPPERS", "5"))
BUY_PROBABILITY = 0.6
THINK_TIME_SECONDS = (0.2, 1.5)
# There are 500 users: IDs 501-520 do not exist and produce the odd realistic 404.
USER_IDS = (1, 520)
REPORT_INTERVAL_SECONDS = 30
# Background noise: every 3-8 min traffic doubles for 30-60 s.
BURSTS = os.getenv("BACKGROUND_NOISE", "on") != "off"
BURST_EVERY_SECONDS = (180, 480)
BURST_DURATION_SECONDS = (30, 60)

log = get_logger("traffic")


async def shopper(client: httpx.AsyncClient, stats: Counter) -> None:
    while True:
        try:
            response = await client.get("/products")
            stats[f"GET /products {response.status_code}"] += 1
            if response.status_code == 200 and random.random() < BUY_PROBABILITY:
                product = random.choice(response.json())
                response = await client.post(
                    "/orders",
                    json={
                        "user_id": random.randint(*USER_IDS),
                        "product_id": product["id"],
                        "quantity": random.randint(1, 3),
                    },
                )
                stats[f"POST /orders {response.status_code}"] += 1
        except httpx.HTTPError as exc:
            stats[f"error {type(exc).__name__}"] += 1
        await asyncio.sleep(random.uniform(*THINK_TIME_SECONDS))


async def bursts(client: httpx.AsyncClient, stats: Counter) -> None:
    while True:
        await asyncio.sleep(random.uniform(*BURST_EVERY_SECONDS))
        extra = [asyncio.create_task(shopper(client, stats)) for _ in range(SHOPPERS)]
        await asyncio.sleep(random.uniform(*BURST_DURATION_SECONDS))
        for task in extra:
            task.cancel()


async def report(stats: Counter) -> None:
    while True:
        await asyncio.sleep(REPORT_INTERVAL_SECONDS)
        log.info("traffic summary", window_seconds=REPORT_INTERVAL_SECONDS, counts=dict(stats))
        stats.clear()


async def main() -> None:
    configure_logging("traffic", os.getenv("LOG_LEVEL", "INFO"))
    log.info("traffic started", shop_url=SHOP_URL, shoppers=SHOPPERS)
    stats: Counter = Counter()
    async with httpx.AsyncClient(base_url=SHOP_URL, timeout=5) as client:
        tasks = [report(stats), *(shopper(client, stats) for _ in range(SHOPPERS))]
        if BURSTS:
            tasks.append(bursts(client, stats))
        await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
