"""Inventory service: catalogue, stock and reservations, with periodic restocking."""

import asyncio
from contextlib import asynccontextmanager, suppress
from uuid import UUID

import asyncpg
from fastapi import HTTPException
from pydantic import BaseModel, Field

from incilot_sim.common.app import create_app
from incilot_sim.common.clients import connect_db
from incilot_sim.common.log import get_logger

SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    id SERIAL PRIMARY KEY,
    sku TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    price_cents INTEGER NOT NULL,
    stock INTEGER NOT NULL CHECK (stock >= 0)
);
CREATE TABLE IF NOT EXISTS reservations (
    order_id UUID PRIMARY KEY,
    product_id INTEGER NOT NULL REFERENCES products (id),
    quantity INTEGER NOT NULL,
    released BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""
CATALOG = [
    ("KB-001", "Mechanical keyboard", 8900),
    ("MS-001", "Wireless mouse", 2900),
    ("MN-001", "Monitor 27''", 24900),
    ("HP-001", "Headphones", 5900),
    ("CM-001", "Webcam HD", 4500),
    ("DK-001", "Dock USB-C", 7900),
    ("CH-001", "Ergonomic chair", 19900),
    ("LP-001", "Laptop stand", 3500),
    ("SS-001", "SSD 1TB", 8500),
    ("CB-001", "HDMI cable", 900),
]
INITIAL_STOCK = 500
RESTOCK_INTERVAL_SECONDS = 30
RESTOCK_BELOW = 100

log = get_logger(__name__)
db: asyncpg.Pool


class Reservation(BaseModel):
    order_id: UUID
    product_id: int
    quantity: int = Field(gt=0)


async def restock_forever() -> None:
    while True:
        await asyncio.sleep(RESTOCK_INTERVAL_SECONDS)
        try:
            rows = await db.fetch(
                "UPDATE products SET stock = $1 WHERE stock < $2 RETURNING sku",
                INITIAL_STOCK,
                RESTOCK_BELOW,
            )
            if rows:
                log.info("restocked", skus=[r["sku"] for r in rows])
        except Exception:
            log.exception("restock failed")


@asynccontextmanager
async def lifespan(_):
    global db
    db = await connect_db(SCHEMA)
    await db.executemany(
        "INSERT INTO products (sku, name, price_cents, stock) VALUES ($1, $2, $3, $4) "
        "ON CONFLICT (sku) DO NOTHING",
        [(*product, INITIAL_STOCK) for product in CATALOG],
    )
    restock = asyncio.create_task(restock_forever())
    yield
    restock.cancel()
    with suppress(asyncio.CancelledError):
        await restock
    await db.close()


app = create_app("inventory", lifespan)


@app.get("/products")
async def list_products():
    rows = await db.fetch("SELECT id, sku, name, price_cents, stock FROM products ORDER BY id")
    return [dict(r) for r in rows]


@app.get("/products/{product_id}")
async def get_product(product_id: int):
    row = await db.fetchrow(
        "SELECT id, sku, name, price_cents, stock FROM products WHERE id = $1", product_id
    )
    if row is None:
        raise HTTPException(404, "product_not_found")
    return dict(row)


@app.post("/reservations", status_code=201)
async def reserve(reservation: Reservation):
    async with db.acquire() as conn, conn.transaction():
        stock = await conn.fetchval(
            "UPDATE products SET stock = stock - $2 WHERE id = $1 AND stock >= $2 RETURNING stock",
            reservation.product_id,
            reservation.quantity,
        )
        if stock is None:
            if await conn.fetchval("SELECT 1 FROM products WHERE id = $1", reservation.product_id):
                raise HTTPException(409, "out_of_stock")
            raise HTTPException(404, "product_not_found")
        await conn.execute(
            "INSERT INTO reservations (order_id, product_id, quantity) VALUES ($1, $2, $3)",
            reservation.order_id,
            reservation.product_id,
            reservation.quantity,
        )
    return {"order_id": reservation.order_id, "remaining_stock": stock}


@app.post("/reservations/{order_id}/release")
async def release(order_id: UUID):
    async with db.acquire() as conn, conn.transaction():
        row = await conn.fetchrow(
            "UPDATE reservations SET released = true WHERE order_id = $1 AND NOT released "
            "RETURNING product_id, quantity",
            order_id,
        )
        if row is None:
            raise HTTPException(404, "reservation_not_found")
        await conn.execute(
            "UPDATE products SET stock = stock + $2 WHERE id = $1",
            row["product_id"],
            row["quantity"],
        )
    log.info("reservation released", order_id=order_id)
    return {"order_id": order_id, "released": True}
