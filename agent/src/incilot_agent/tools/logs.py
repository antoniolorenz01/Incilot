"""Logs de Loki, con filtros tipados (no LogQL libre)."""

import json
import time
from typing import Literal

from incilot_agent import config
from incilot_agent.tools import _http
from incilot_agent.tools._guard import ToolError, guarded

SERVICES = {"shop", "users", "inventory", "payments", "traffic", "postgres", "redis"}
MAX_LINE = 500
Level = Literal["info", "warning", "error"]


@guarded(timeout=15)
async def search_logs(
    service: str | None = None,
    level: Level | None = None,
    contains: str | None = None,
    minutes: int = 15,
    limit: int = 50,
) -> str:
    """Busca logs de los últimos `minutes` minutos, del más nuevo al más viejo.

    service: shop, users, inventory, payments, traffic, postgres o redis (todos si se omite).
    level: info, warning o error. contains: texto que debe aparecer en la línea.
    Los servicios loguean JSON con `msg`, `request_id` y campos propios; postgres y
    redis loguean en su formato de texto.
    """
    if service is not None and service not in SERVICES:
        raise ToolError(f"servicio desconocido: {service}. Opciones: {', '.join(sorted(SERVICES))}")
    if not 1 <= minutes <= 24 * 60 or not 1 <= limit <= 200:
        raise ToolError("minutes tiene que estar entre 1 y 1440, y limit entre 1 y 200")

    selector = [f'service="{service}"' if service else 'service=~".+"']
    if level:
        selector.append(f'level="{level}"')
    query = "{" + ", ".join(selector) + "}"
    if contains:
        query += " |= " + json.dumps(contains)  # comillas y escapes válidos en LogQL

    end = time.time_ns()
    async with _http.client(config.LOKI_URL) as http:
        response = await http.get(
            "/loki/api/v1/query_range",
            params={
                "query": query,
                "start": end - minutes * 60 * 10**9,
                "end": end,
                "limit": limit,
                "direction": "backward",
            },
        )
    if response.status_code != 200:
        raise ToolError(f"Loki rechazó la consulta: {response.text[:300]}")

    entries = [
        (int(ts), stream["stream"].get("service", "?"), line)
        for stream in response.json()["data"]["result"]
        for ts, line in stream["values"]
    ]
    if not entries:
        return f"sin logs para {query} en los últimos {minutes} min"
    entries.sort(reverse=True)
    lines = [f"{len(entries)} líneas para {query} (más nuevas primero):"]
    for ts, svc, line in entries[:limit]:
        when = time.strftime("%H:%M:%S", time.gmtime(ts / 10**9))
        lines.append(f"{when} [{svc}] {line[:MAX_LINE]}")
    return "\n".join(lines)
