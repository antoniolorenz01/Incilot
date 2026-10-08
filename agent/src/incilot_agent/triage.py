"""Triage: what changed in the system, without an LLM.

It is deterministic and free. It compares each key metric since the incident started
(or over the last 5 minutes, if the alert does not say when) with its baseline (the
previous hour) and splits the error patterns in the logs into new, growing and stable.
That way the agent starts out knowing what changed, and does not mistake background
noise (errors that are always there) or a previous, already resolved incident for this
one.
"""

import asyncio
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

import httpx

from incilot_agent import config
from incilot_agent.tools import _http
from incilot_agent.tools.logs import signature

RECENT_DEFAULT = 5 * 60  # seconds, when the start of the incident is unknown
RECENT_MIN, RECENT_MAX = 60, 30 * 60
BASELINE = "45m"  # the previous hour, leaving a 5-minute margin before the recent window
BASELINE_MARGIN = 5 * 60
# During a big incident Loki holds thousands of error lines a minute: give it time.
LOGS_TIMEOUT_SECONDS = 30
CHANGE_RATIO = 2.0  # changed if multiplied (or divided) by at least this…


@dataclass(frozen=True)
class Metric:
    title: str
    query: str  # instant, with rate(…[1m]); averaged per window
    labels: tuple[str, ...]
    min_delta: float  # …and also moved by at least this in absolute terms
    unit: str = ""


METRICS = [
    Metric(
        "5xx error rate",
        'sum by (service) (rate(http_requests_total{status=~"5.."}[1m]))'
        " / sum by (service) (rate(http_requests_total[1m]))",
        ("service",),
        0.02,
    ),
    Metric(
        "p95 latency",
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
        "unsuccessful shop calls (/s)",
        'sum by (target, status) (rate(upstream_requests_total{service="shop",'
        'status=~"timeout|error|5..|429"}[1m]))',
        ("target", "status"),
        0.1,
    ),
    Metric(
        "failed orders (/s)",
        'sum by (reason) (rate(orders_total{status!="confirmed"}[1m]))',
        ("reason",),
        0.1,
    ),
    Metric(
        "memory",
        "process_resident_memory_bytes / 1e6",
        ("service",),
        30,
        "MB",
    ),
]


def changed(recent: float, baseline: float | None, min_delta: float) -> bool:
    if baseline is None:
        return recent >= min_delta  # did not exist before and is relevant now
    if abs(recent - baseline) < min_delta:
        return False
    low, high = sorted((recent, baseline))
    return low == 0 or high / low >= CHANGE_RATIO


def _describe(metric: Metric, labels: dict, recent: float, baseline: float | None) -> str:
    who = " · ".join(labels.get(k, "?") for k in metric.labels)
    now = f"{recent:.3g}{metric.unit}"
    if baseline is None:
        return f"↑ {metric.title} · {who}: {now} (none before)"
    arrow = "↑" if recent > baseline else "↓" if recent < baseline else "="
    factor = f" ×{recent / baseline:.3g}" if baseline else ""
    return f"{arrow} {metric.title} · {who}: {now} (before {baseline:.3g}{metric.unit}){factor}"


async def _vector(http, query: str) -> dict[tuple, tuple[dict, float]]:
    body = (await http.get("/api/v1/query", params={"query": query})).json()
    result = {}
    for series in body.get("data", {}).get("result", []):
        value = float(series["value"][1])
        if value == value:  # NaN: no data
            result[tuple(sorted(series["metric"].items()))] = (series["metric"], value)
    return result


def recent_seconds(since: datetime | None) -> int:
    """The incident's window: from its start until now (clamped), or the last 5 minutes."""
    if since is None:
        return RECENT_DEFAULT
    elapsed = int(time.time() - since.timestamp())
    return min(max(elapsed, RECENT_MIN), RECENT_MAX)


async def metric_changes(recent: int = RECENT_DEFAULT) -> tuple[list[str], list[str]]:
    """(changes, stable) for each metric, the last `recent` seconds versus baseline."""
    changes, stable = [], []
    offset = recent + BASELINE_MARGIN
    async with _http.client(config.PROMETHEUS_URL) as http:
        for metric in METRICS:
            recent_q = f"avg_over_time(({metric.query})[{recent}s:15s])"
            base_q = f"avg_over_time(({metric.query})[{BASELINE}:1m] offset {offset}s)"
            recent, base = await asyncio.gather(_vector(http, recent_q), _vector(http, base_q))
            for key, (labels, value) in recent.items():
                baseline = base.get(key, (None, None))[1]
                line = _describe(metric, labels, value, baseline)
                (changes if changed(value, baseline, metric.min_delta) else stable).append(line)
    changes.sort(key=lambda line: not line.startswith("↑"))  # what went up, first
    return changes, stable


async def log_changes(limit: int = 8, recent: int = RECENT_DEFAULT) -> list[str]:
    """Error patterns from the last `recent` seconds versus the hour before: new and
    growing first, then stable. A previous incident's errors fall in the hour before,
    so they do not show up as new."""
    end = time.time_ns()
    recent_since = end - recent * 10**9
    start = recent_since - 60 * 60 * 10**9
    async with _http.client(config.LOKI_URL) as http:
        http.timeout = httpx.Timeout(LOGS_TIMEOUT_SECONDS)
        response = await http.get(
            "/loki/api/v1/query_range",
            params={
                "query": '{service=~".+", level="error"}',
                "start": start,
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
        before_rate = g["before"] / 60  # per minute
        if g["recent"] and not g["before"]:
            return "NEW"
        if g["recent"] / (recent / 60) >= 3 * max(before_rate, 0.2):
            return "GROWING"
        return "stable"

    window = _window(recent)
    order = {"NEW": 0, "GROWING": 1, "stable": 2}
    ranked = sorted(groups.values(), key=lambda g: (order[kind(g)], -g["recent"]))
    return [
        f"{kind(g):7} {window}: {g['recent']}× · the hour before: {g['before']}×\n"
        f"        example: {g['example']}"
        for g in ranked[:limit]
        if g["recent"] or kind(g) != "stable"
    ]


def _failure(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}".rstrip(": ")


def _window(seconds: int) -> str:
    return f"last {seconds // 60} min" if seconds % 60 == 0 else f"last {seconds}s"


async def overview(since: datetime | None = None) -> str:
    """The triage summary. `since`: when the incident started, if the alert says so."""
    recent = recent_seconds(since)
    metrics, logs = await asyncio.gather(
        metric_changes(recent), log_changes(recent=recent), return_exceptions=True
    )
    # Triage only gives the agent a head start: if a source fails, it says so and the
    # agent investigates with its tools anyway.
    changes, stable = (
        ([f"(metrics unavailable: {_failure(metrics)}; check them with the tools)"], [])
        if isinstance(metrics, BaseException)
        else metrics
    )
    if isinstance(logs, BaseException):
        logs = [f"(logs unavailable: {_failure(logs)}; search them with the tools)"]
    window = f"since {since:%H:%M:%S} UTC" if since else _window(recent)
    sections = [
        f"## What changed {window} compared with the hour before (↑ up, ↓ down)",
        "\n".join(f"- {c}" for c in changes) or "- nothing changed significantly",
        "## Unchanged (normal baseline)",
        "\n".join(f"- {s}" for s in stable[:20]) or "- (no data)",
        "## Errors in the logs: new and growing first; stable ones are background noise",
        "\n".join(logs) or "no errors in the last hour",
    ]
    return "\n\n".join(sections)
