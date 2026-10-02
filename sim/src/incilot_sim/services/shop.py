"""Tienda: punto de entrada de los clientes. Orquesta usuarios, inventario y pagos."""

import json
import os
from contextlib import asynccontextmanager
from uuid import UUID, uuid4

import asyncpg
import httpx
from fastapi import HTTPException
from prometheus_client import Counter
from pydantic import BaseModel, Field
from redis.asyncio import Redis

from incilot_sim.common.app import create_app
from incilot_sim.common.clients import Upstream, connect_cache, connect_db
from incilot_sim.common.log import get_logger

SCHEMA = """
CREATE TABLE IF NOT EXISTS orders (
    id UUID PRIMARY KEY,
    user_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    quantity INTEGER NOT NULL,
    amount_cents INTEGER NOT NULL,
    status TEXT NOT NULL,
    failure_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""
CATALOG_CACHE_TTL_SECONDS = 30

ORDERS = Counter("orders_total", "Pedidos procesados por resultado", ["status", "reason"])

log = get_logger(__name__)
db: asyncpg.Pool
cache: Redis
users = Upstream("users", os.getenv("USERS_URL", "http://users:8000"))
inventory = Upstream("inventory", os.getenv("INVENTORY_URL", "http://inventory:8000"))
payments = Upstream("payments", os.getenv("PAYMENTS_URL", "http://payments:8000"))


class OrderIn(BaseModel):
    user_id: int
    product_id: int
    quantity: int = Field(default=1, gt=0, le=10)


@asynccontextmanager
async def lifespan(_):
    global db, cache
    db = await connect_db(SCHEMA)
    cache = connect_cache()
    yield
    for upstream in (users, inventory, payments):
        await upstream.aclose()
    await cache.aclose()
    await db.close()


app = create_app("shop", lifespan)


async def call(upstream: Upstream, method: str, path: str, **kwargs) -> httpx.Response:
    """Llama a otro servicio; si no responde o falla con 5xx, la tienda devuelve 502."""
    try:
        response = await upstream.request(method, path, **kwargs)
    except httpx.HTTPError as exc:
        log.error("upstream unavailable", target=upstream.name, error=repr(exc))
        raise HTTPException(502, f"{upstream.name}_unavailable") from exc
    if response.status_code >= 500:
        log.error("upstream error", target=upstream.name, status=response.status_code)
        raise HTTPException(502, f"{upstream.name}_error")
    return response


async def fail_order(order_id: UUID, status_code: int, reason: str) -> HTTPException:
    await db.execute(
        "UPDATE orders SET status = 'failed', failure_reason = $2, updated_at = now() "
        "WHERE id = $1",
        order_id,
        reason,
    )
    ORDERS.labels("failed", reason).inc()
    log.warning("order failed", order_id=order_id, reason=reason)
    return HTTPException(status_code, reason)


@app.get("/products")
async def list_products():
    if cached := await cache.get("catalog"):
        return json.loads(cached)
    products = (await call(inventory, "GET", "/products")).json()
    await cache.set("catalog", json.dumps(products), ex=CATALOG_CACHE_TTL_SECONDS)
    return products


@app.post("/orders", status_code=201)
async def create_order(order: OrderIn):
    if (await call(users, "GET", f"/users/{order.user_id}")).status_code == 404:
        ORDERS.labels("rejected", "user_not_found").inc()
        raise HTTPException(404, "user_not_found")
    product = await call(inventory, "GET", f"/products/{order.product_id}")
    if product.status_code == 404:
        ORDERS.labels("rejected", "product_not_found").inc()
        raise HTTPException(404, "product_not_found")

    order_id = uuid4()
    amount_cents = product.json()["price_cents"] * order.quantity
    await db.execute(
        "INSERT INTO orders (id, user_id, product_id, quantity, amount_cents, status) "
        "VALUES ($1, $2, $3, $4, $5, 'pending')",
        order_id,
        order.user_id,
        order.product_id,
        order.quantity,
        amount_cents,
    )

    try:
        reservation = await call(
            inventory,
            "POST",
            "/reservations",
            json={
                "order_id": str(order_id),
                "product_id": order.product_id,
                "quantity": order.quantity,
            },
        )
    except HTTPException as exc:
        raise await fail_order(order_id, 502, "inventory_unavailable") from exc
    if reservation.status_code == 409:
        raise await fail_order(order_id, 409, "out_of_stock")

    try:
        charge = await call(
            payments,
            "POST",
            "/charges",
            json={
                "order_id": str(order_id),
                "user_id": order.user_id,
                "amount_cents": amount_cents,
            },
        )
    except HTTPException as exc:
        await release_reservation(order_id)
        raise await fail_order(order_id, 502, "payments_unavailable") from exc
    if charge.status_code == 402:
        await release_reservation(order_id)
        raise await fail_order(order_id, 402, "payment_declined")

    await db.execute(
        "UPDATE orders SET status = 'confirmed', updated_at = now() WHERE id = $1", order_id
    )
    ORDERS.labels("confirmed", "").inc()
    log.info("order confirmed", order_id=order_id, amount_cents=amount_cents)
    return {"order_id": order_id, "status": "confirmed", "amount_cents": amount_cents}


async def release_reservation(order_id: UUID) -> None:
    """Devuelve el stock reservado. Si falla, se loguea y el pedido sigue su curso."""
    try:
        await call(inventory, "POST", f"/reservations/{order_id}/release")
    except HTTPException:
        log.error("reservation release failed", order_id=order_id)


@app.get("/orders/{order_id}")
async def get_order(order_id: UUID):
    row = await db.fetchrow("SELECT * FROM orders WHERE id = $1", order_id)
    if row is None:
        raise HTTPException(404, "order_not_found")
    return dict(row)
