"""Triage: un resumen del estado del sistema, sin LLM.

Es determinístico y gratis: le da al agente un punto de partida (qué servicios tienen
errores o latencia, qué dependencias fallan desde shop y los errores recientes) antes
de que gaste pasos en descubrirlo.
"""

import asyncio

from incilot_agent.tools import query_metrics, search_logs

OVERVIEW = {
    "Tasa de errores 5xx por servicio": (
        'sum by (service) (rate(http_requests_total{status=~"5.."}[2m]))'
        " / sum by (service) (rate(http_requests_total[2m]))"
    ),
    "Latencia p95 por servicio (s)": (
        "histogram_quantile(0.95, sum by (service, le) "
        "(rate(http_request_duration_seconds_bucket[2m])))"
    ),
    "Llamadas de shop a sus dependencias por resultado (req/s)": (
        'sum by (target, status) (rate(upstream_requests_total{service="shop"}[2m]))'
    ),
    "Pedidos por resultado (req/s)": "sum by (status, reason) (rate(orders_total[2m]))",
}


async def overview() -> str:
    metrics = await asyncio.gather(*(query_metrics(q, minutes=15) for q in OVERVIEW.values()))
    errors = await search_logs(level="error", minutes=10, limit=15)
    sections = [f"## {title}\n{result}" for title, result in zip(OVERVIEW, metrics, strict=True)]
    sections.append(f"## Errores recientes en los logs\n{errors}")
    return "\n\n".join(sections)
