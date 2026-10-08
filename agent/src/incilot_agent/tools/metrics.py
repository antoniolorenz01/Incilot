"""Prometheus metrics."""

import time

from incilot_agent import config
from incilot_agent.tools import _http
from incilot_agent.tools._guard import ToolError, guarded

MAX_SERIES = 20


@guarded(timeout=15)
async def query_metrics(promql: str, minutes: int = 15, step_seconds: int = 30) -> str:
    """Query Prometheus with PromQL over the last `minutes` minutes.

    Returns, per series, its labels and the current, minimum, maximum and average value.
    Useful metrics: http_requests_total, http_request_duration_seconds_bucket,
    upstream_requests_total, upstream_request_duration_seconds_bucket, orders_total,
    process_resident_memory_bytes. All of them have the `service` label.
    """
    if not 1 <= minutes <= 24 * 60:
        raise ToolError("minutes must be between 1 and 1440")
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
        raise ToolError(f"Prometheus rejected the query: {body.get('error', response.text)}")
    series = body["data"]["result"]
    if not series:
        return "no data for that query in the requested window"

    lines = [f"{len(series)} series, last {minutes} min:"]
    for s in series[:MAX_SERIES]:
        values = [float(v) for _, v in s["values"] if v not in ("NaN", "+Inf", "-Inf")]
        labels = ", ".join(f"{k}={v}" for k, v in sorted(s["metric"].items())) or "(no labels)"
        if not values:
            lines.append(f"- {labels}: no numeric values")
            continue
        lines.append(
            f"- {labels}: current {values[-1]:.4g} | min {min(values):.4g} | "
            f"max {max(values):.4g} | avg {sum(values) / len(values):.4g}"
        )
    if len(series) > MAX_SERIES:
        lines.append(f"… and {len(series) - MAX_SERIES} more series: add filters or a sum by")
    return "\n".join(lines)
