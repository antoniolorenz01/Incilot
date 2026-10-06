# ruff: noqa: E501  (los tracebacks son texto literal)
"""Ruido de fondo: lo que pasa en cualquier sistema real aunque no haya un incidente.

Errores transitorios sueltos y picos de latencia ocasionales, con la misma forma que
los síntomas reales, para que una anomalía no salte a la vista solo por romper una
línea base perfecta. Se apaga con BACKGROUND_NOISE=off.
"""

import asyncio
import os
import random

from fastapi import Request

from incilot_sim.common.faults import UNAFFECTED_PATHS, InjectedError

ENABLED = os.getenv("BACKGROUND_NOISE", "on") != "off"
TRANSIENT_ERROR_RATE = 0.003
LATENCY_SPIKE_RATE = 0.01
LATENCY_SPIKE_SECONDS = (0.2, 0.8)

TRANSIENT_TRACEBACKS = [
    """Traceback (most recent call last):
  File "/usr/local/lib/python3.12/site-packages/asyncpg/pool.py", line 1061, in __aexit__
    await self.pool.release(con)
asyncpg.exceptions.ConnectionDoesNotExistError: connection was closed in the middle of operation
""",
    """Traceback (most recent call last):
  File "/usr/local/lib/python3.12/site-packages/redis/asyncio/connection.py", line 569, in read_response
    response = await self._parser.read_response(disable_decoding=disable_decoding)
redis.exceptions.ConnectionError: Error while reading from redis:6379 : (104, 'Connection reset by peer')
""",
    """Traceback (most recent call last):
  File "/usr/local/lib/python3.12/asyncio/selector_events.py", line 1003, in _read_ready__data_received
    data = self._sock.recv(self.max_size)
ConnectionResetError: [Errno 104] Connection reset by peer
""",
]


async def disturb(request: Request) -> None:
    """Dependencia global de FastAPI, como los interruptores de fallos."""
    if request.url.path in UNAFFECTED_PATHS:
        return
    if random.random() < LATENCY_SPIKE_RATE:
        await asyncio.sleep(random.uniform(*LATENCY_SPIKE_SECONDS))
    if random.random() < TRANSIENT_ERROR_RATE:
        raise InjectedError(random.choice(TRANSIENT_TRACEBACKS))
