"""Servicio de pagos: simula un proveedor externo con latencia y rechazos."""

import asyncio
import os
import random
from contextlib import asynccontextmanager
from uuid import UUID

import asyncpg
from fastapi import HTTPException
from pydantic import BaseModel, Field

from incilot_sim.common.app import create_app
from incilot_sim.common.clients import connect_db
from incilot_sim.common.log import get_logger

SCHEMA = """
CREATE TABLE IF NOT EXISTS payments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id UUID UNIQUE NOT NULL,
    user_id INTEGER NOT NULL,
    amount_cents INTEGER NOT NULL,
    status TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""
DECLINE_RATE = float(os.getenv("PAYMENTS_DECLINE_RATE", "0.03"))
PROVIDER_LATENCY_SECONDS = (0.05, 0.2)

log = get_logger(__name__)
db: asyncpg.Pool


class Charge(BaseModel):
    order_id: UUID
    user_id: int
    amount_cents: int = Field(gt=0)


@asynccontextmanager
async def lifespan(_):
    global db
    db = await connect_db(SCHEMA)
    yield
    await db.close()


app = create_app("payments", lifespan)


@app.post("/charges", status_code=201)
async def charge(charge: Charge):
    await asyncio.sleep(random.uniform(*PROVIDER_LATENCY_SECONDS))
    status = "declined" if random.random() < DECLINE_RATE else "captured"
    try:
        payment_id = await db.fetchval(
            "INSERT INTO payments (order_id, user_id, amount_cents, status) "
            "VALUES ($1, $2, $3, $4) RETURNING id",
            charge.order_id,
            charge.user_id,
            charge.amount_cents,
            status,
        )
    except asyncpg.UniqueViolationError:
        raise HTTPException(409, "duplicate_charge") from None
    if status == "declined":
        log.warning("payment declined", order_id=charge.order_id, reason="card_declined")
        raise HTTPException(402, "card_declined")
    return {"payment_id": payment_id, "status": status}
