"""Triage: qué cambió en el sistema, sin LLM.

Es determinístico y gratis. Compara cada métrica clave en los últimos 5 minutos contra
su línea base (la hora anterior) y separa los patrones de error de los logs en nuevos,
crecientes y estables. Así el agente arranca sabiendo qué cambió, y no confunde el ruido
de fondo (errores que existen siempre) con el incidente.
"""

import asyncio
import time
from collections import defaultdict
from dataclasses import dataclass

from incilot_agent import config
from incilot_agent.tools import _http
from incilot_agent.tools.logs import signature

RECENT = "5m"
BASELINE = "45m"  # la hora anterior, dejando 10 min de margen
BASELINE_OFFSET = "10m"
CHANGE_RATIO = 2.0  # cambió si se multiplicó (o dividió) por al menos esto…


@dataclass(frozen=True)
class Metric:
    title: str
    query: str  # instantáneo, con rate(…[1m]); se promedia por ventana
    labels: tuple[str, ...]
    min_delta: float  # …y además se movió al menos esto en valor absoluto
    unit: str = ""


METRICS = [
    Metric(
        "tasa de errores 5xx",
        'sum by (service) (rate(http_requests_total{status=~"5.."}[1m]))'
        " / sum by (service) (rate(http_requests_total[1m]))",
        ("service",),
        0.02,
    ),
    Metric(
        "latencia p95",
        "histogram_quantile(0.95, sum by (service, le) "
        "(rate(http_request_duration_seconds_bucket[1m])))",
        ("service",),
        0.05,
        "s",
    ),
    Metric(
        "requests/s",
        "sum by (service) (rate(http_requests_total[1m]))",
        ("service",),
        1.0,
    ),
    Metric(
        "llamadas de shop sin éxito (/s)",
        'sum by (target, status) (rate(upstream_requests_total{service="shop",'
        'status=~"timeout|error|5..|429"}[1m]))',
        ("target", "status"),
        0.1,
    ),
    Metric(
        "pedidos fallidos (/s)",
        'sum by (reason) (rate(orders_total{status!="confirmed"}[1m]))',
        ("reason",),
        0.1,
    ),
    Metric(
        "memoria",
        "process_resident_memory_bytes / 1e6",
        ("service",),
        30,
        "MB",
    ),
]


def changed(recent: float, baseline: float | None, min_delta: float) -> bool:
    if baseline is None:
        return recent >= min_delta  # no existía antes y ahora es relevante
    if abs(recent - baseline) < min_delta:
        return False
    low, high = sorted((recent, baseline))
    return low == 0 or high / low >= CHANGE_RATIO


def _describe(metric: Metric, labels: dict, recent: float, baseline: float | None) -> str:
    who = " · ".join(labels.get(k, "?") for k in metric.labels)
    now = f"{recent:.3g}{metric.unit}"
    if baseline is None:
        return f"↑ {metric.title} · {who}: {now} (no había antes)"
    arrow = "↑" if recent > baseline else "↓" if recent < baseline else "="
    factor = f" ×{recent / baseline:.3g}" if baseline else ""
    return f"{arrow} {metric.title} · {who}: {now} (antes {baseline:.3g}{metric.unit}){factor}"


async def _vector(http, query: str) -> dict[tuple, tuple[dict, float]]:
    body = (await http.get("/api/v1/query", params={"query": query})).json()
    result = {}
    for series in body.get("data", {}).get("result", []):
        value = float(series["value"][1])
        if value == value:  # NaN: sin datos
            result[tuple(sorted(series["metric"].items()))] = (series["metric"], value)
    return result


async def metric_changes() -> tuple[list[str], list[str]]:
    """(cambios, estables) de cada métrica, recientes contra línea base."""
    changes, stable = [], []
    async with _http.client(config.PROMETHEUS_URL) as http:
        for metric in METRICS:
            recent_q = f"avg_over_time(({metric.query})[{RECENT}:15s])"
            base_q = f"avg_over_time(({metric.query})[{BASELINE}:1m] offset {BASELINE_OFFSET})"
            recent, base = await asyncio.gather(_vector(http, recent_q), _vector(http, base_q))
            for key, (labels, value) in recent.items():
                baseline = base.get(key, (None, None))[1]
                line = _describe(metric, labels, value, baseline)
                (changes if changed(value, baseline, metric.min_delta) else stable).append(line)
    changes.sort(key=lambda line: not line.startswith("↑"))  # lo que subió, primero
    return changes, stable


async def log_changes(limit: int = 8) -> list[str]:
    """Patrones de error de la última hora: nuevos y crecientes primero, después estables."""
    end = time.time_ns()
    recent_since = end - 5 * 60 * 10**9
    async with _http.client(config.LOKI_URL) as http:
        response = await http.get(
            "/loki/api/v1/query_range",
            params={
                "query": '{service=~".+", level="error"}',
                "start": end - 60 * 60 * 10**9,
                "end": end,
                "limit": 2000,
                "direction": "backward",
            },
        )
    groups: dict[str, dict] = defaultdict(lambda: {"recent": 0, "before": 0, "example": ""})
    for stream in response.json()["data"]["result"]:
        service = stream["stream"].get("service", "?")
        for ts, line in stream["values"]:
            group = groups[signature(service, line)]
            group["recent" if int(ts) >= recent_since else "before"] += 1
            group["example"] = group["example"] or f"[{service}] {line[:300]}"

    def kind(g: dict) -> str:
        before_rate = g["before"] / 55  # por minuto, para comparar con los últimos 5
        if g["recent"] and not g["before"]:
            return "NUEVO"
        if g["recent"] / 5 >= 3 * max(before_rate, 0.2):
            return "CRECIÓ"
        return "estable"

    order = {"NUEVO": 0, "CRECIÓ": 1, "estable": 2}
    ranked = sorted(groups.values(), key=lambda g: (order[kind(g)], -g["recent"]))
    return [
        f"{kind(g):7} últimos 5 min: {g['recent']}× · hora anterior: {g['before']}×\n"
        f"        ej: {g['example']}"
        for g in ranked[:limit]
        if g["recent"] or kind(g) != "estable"
    ]


async def overview() -> str:
    (changes, stable), logs = await asyncio.gather(metric_changes(), log_changes())
    sections = [
        "## Qué cambió en los últimos 5 min respecto de la hora anterior (↑ subió, ↓ bajó)",
        "\n".join(f"- {c}" for c in changes) or "- nada cambió de forma significativa",
        "## Sin cambios (línea base normal)",
        "\n".join(f"- {s}" for s in stable[:20]) or "- (sin datos)",
        "## Errores en los logs: nuevos y crecientes primero; los estables son ruido de fondo",
        "\n".join(logs) or "sin errores en la última hora",
    ]
    return "\n\n".join(sections)
