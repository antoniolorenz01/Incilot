"""Logs de Loki, con filtros tipados (no LogQL libre) y agrupados por patrón.

Un incidente repite el mismo error cientos de veces: en vez de pasarle al agente
cientos de líneas, se agrupan por su "firma" (servicio, nivel, mensaje, ruta, status,
destino y el tipo de error del traceback, con números e ids normalizados) y se muestra
cada patrón una vez, con cuántas veces apareció, cuándo y un ejemplo completo.
"""

import json
import re
import time
from collections import defaultdict
from typing import Literal

from incilot_agent import config
from incilot_agent.tools import _http
from incilot_agent.tools._guard import ToolError, guarded

SERVICES = {"shop", "users", "inventory", "payments", "traffic", "postgres", "redis"}
MAX_LINE = 500
FETCH_LIMIT = 1000  # líneas que se piden a Loki para agrupar
# Campos que cambian en cada repetición del mismo evento: no forman parte de la firma.
VOLATILE = {"ts", "request_id", "duration_ms", "order_id", "amount_cents", "user_id",
            "payment_id", "remaining_stock", "counts", "window_seconds", "logger"}  # fmt: skip
IDS = re.compile(
    r"\b[0-9a-f]{8}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{12}\b|\b[0-9a-f]{12,}\b"
)
NUMBERS = re.compile(r"\d+(\.\d+)?")
Level = Literal["info", "warning", "error"]


@guarded(timeout=15)
async def search_logs(
    service: str | None = None,
    level: Level | None = None,
    contains: str | None = None,
    minutes: int = 15,
    limit: int = 15,
) -> str:
    """Busca logs de los últimos `minutes` minutos, agrupados por patrón: cada patrón
    aparece una vez, con cuántas veces se repitió, entre qué horas y un ejemplo completo.
    `limit` es la cantidad máxima de patrones (los más frecuentes).

    service: shop, users, inventory, payments, traffic, postgres o redis (todos si se omite).
    level: info, warning o error. contains: texto que debe aparecer en la línea.
    Los servicios loguean JSON con `msg`, `request_id` y campos propios; postgres y
    redis loguean en su formato de texto.
    """
    if service is not None and service not in SERVICES:
        raise ToolError(f"servicio desconocido: {service}. Opciones: {', '.join(sorted(SERVICES))}")
    if not 1 <= minutes <= 24 * 60 or not 1 <= limit <= 50:
        raise ToolError("minutes tiene que estar entre 1 y 1440, y limit entre 1 y 50")

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
                "limit": FETCH_LIMIT,
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
    return summarize(entries, query, minutes, limit)


def signature(service: str, line: str) -> str:
    """Lo que identifica al evento, sin lo que cambia en cada repetición."""
    try:
        entry = json.loads(line)
    except ValueError:
        return NUMBERS.sub("<n>", IDS.sub("<id>", f"{service} {line}"))
    parts = [service, entry.get("level", ""), entry.get("msg", "")]
    parts += [
        f"{key}={value}"
        for key, value in sorted(entry.items())
        if key not in VOLATILE and key not in {"service", "level", "msg", "exc"}
    ]
    if exc := entry.get("exc"):
        parts.append(exc.strip().splitlines()[-1])  # el tipo y mensaje del error
    return NUMBERS.sub("<n>", IDS.sub("<id>", " ".join(map(str, parts))))


def summarize(entries: list[tuple[int, str, str]], query: str, minutes: int, limit: int) -> str:
    groups: dict[str, list[tuple[int, str, str]]] = defaultdict(list)
    for entry in entries:
        groups[signature(entry[1], entry[2])].append(entry)
    ranked = sorted(groups.values(), key=lambda g: (len(g), max(e[0] for e in g)), reverse=True)

    def clock(ts: int) -> str:
        return time.strftime("%H:%M:%S", time.gmtime(ts / 10**9))

    lines = [
        f"{len(entries)} líneas en {len(groups)} patrones para {query}, últimos {minutes} min "
        "(más frecuentes primero):"
    ]
    for group in ranked[:limit]:
        times = [e[0] for e in group]
        newest = max(group)
        lines.append(
            f"\n{len(group)}× [{newest[1]}] entre {clock(min(times))} y {clock(max(times))}\n"
            f"   ej: {newest[2][:MAX_LINE]}"
        )
    if len(ranked) > limit:
        rest = sum(len(g) for g in ranked[limit:])
        lines.append(f"\n… y {len(ranked) - limit} patrones más ({rest} líneas): filtrá más")
    return "\n".join(lines)
