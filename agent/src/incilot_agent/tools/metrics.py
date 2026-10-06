"""Métricas de Prometheus."""

import time

from incilot_agent import config
from incilot_agent.tools import _http
from incilot_agent.tools._guard import ToolError, guarded

MAX_SERIES = 20


@guarded(timeout=15)
async def query_metrics(promql: str, minutes: int = 15, step_seconds: int = 30) -> str:
    """Consulta Prometheus con PromQL en los últimos `minutes` minutos.

    Devuelve, por serie, sus etiquetas y el valor actual, mínimo, máximo y promedio.
    Métricas útiles: http_requests_total, http_request_duration_seconds_bucket,
    upstream_requests_total, upstream_request_duration_seconds_bucket, orders_total,
    process_resident_memory_bytes. Todas tienen la etiqueta `service`.
    """
    if not 1 <= minutes <= 24 * 60:
        raise ToolError("minutes tiene que estar entre 1 y 1440")
    end = time.time()
    async with _http.client(config.PROMETHEUS_URL) as http:
        response = await http.get(
            "/api/v1/query_range",
            params={
                "query": promql,
                "start": end - minutes * 60,
                "end": end,
                "step": step_seconds,
            },
        )
    body = response.json()
    if body.get("status") != "success":
        raise ToolError(f"Prometheus rechazó la consulta: {body.get('error', response.text)}")
    series = body["data"]["result"]
    if not series:
        return "sin datos para esa consulta en la ventana pedida"

    lines = [f"{len(series)} series, últimos {minutes} min:"]
    for s in series[:MAX_SERIES]:
        values = [float(v) for _, v in s["values"] if v not in ("NaN", "+Inf", "-Inf")]
        labels = ", ".join(f"{k}={v}" for k, v in sorted(s["metric"].items())) or "(sin etiquetas)"
        if not values:
            lines.append(f"- {labels}: sin valores numéricos")
            continue
        lines.append(
            f"- {labels}: actual {values[-1]:.4g} | min {min(values):.4g} | "
            f"max {max(values):.4g} | prom {sum(values) / len(values):.4g}"
        )
    if len(series) > MAX_SERIES:
        lines.append(f"… y {len(series) - MAX_SERIES} series más: agregá filtros o un sum by")
    return "\n".join(lines)
