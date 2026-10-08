"""Loki logs, with typed filters (not free-form LogQL) and grouped by pattern.

An incident repeats the same error hundreds of times: instead of passing the agent
hundreds of lines, they are grouped by their "signature" (service, level, message, path,
status, target and the traceback's error type, with numbers and ids normalised) and each
pattern is shown once, with how many times it appeared, when, and a full example.
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
FETCH_LIMIT = 1000  # lines requested from Loki for grouping
# Fields that change with every repetition of the same event: not part of the signature.
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
    """Search logs from the last `minutes` minutes, grouped by pattern: each pattern
    appears once, with how many times it repeated, between which times, and a full
    example. `limit` is the maximum number of patterns (the most frequent ones).

    service: shop, users, inventory, payments, traffic, postgres or redis (all if omitted).
    level: info, warning or error. contains: text that must appear in the line.
    The services log JSON with `msg`, `request_id` and their own fields; postgres and
    redis log in their own text format.
    """
    if service is not None and service not in SERVICES:
        raise ToolError(f"unknown service: {service}. Options: {', '.join(sorted(SERVICES))}")
    if not 1 <= minutes <= 24 * 60 or not 1 <= limit <= 50:
        raise ToolError("minutes must be between 1 and 1440, and limit between 1 and 50")

    selector = [f'service="{service}"' if service else 'service=~".+"']
    if level:
        selector.append(f'level="{level}"')
    query = "{" + ", ".join(selector) + "}"
    if contains:
        query += " |= " + json.dumps(contains)  # valid LogQL quoting and escaping

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
        raise ToolError(f"Loki rejected the query: {response.text[:300]}")

    entries = [
        (int(ts), stream["stream"].get("service", "?"), line)
        for stream in response.json()["data"]["result"]
        for ts, line in stream["values"]
    ]
    if not entries:
        return f"no logs for {query} in the last {minutes} min"
    return summarize(entries, query, minutes, limit)


def signature(service: str, line: str) -> str:
    """What identifies the event, without what changes on each repetition."""
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
        parts.append(exc.strip().splitlines()[-1])  # the error's type and message
    return NUMBERS.sub("<n>", IDS.sub("<id>", " ".join(map(str, parts))))


def summarize(entries: list[tuple[int, str, str]], query: str, minutes: int, limit: int) -> str:
    groups: dict[str, list[tuple[int, str, str]]] = defaultdict(list)
    for entry in entries:
        groups[signature(entry[1], entry[2])].append(entry)
    ranked = sorted(groups.values(), key=lambda g: (len(g), max(e[0] for e in g)), reverse=True)

    def clock(ts: int) -> str:
        return time.strftime("%H:%M:%S", time.gmtime(ts / 10**9))

    lines = [
        f"{len(entries)} lines in {len(groups)} patterns for {query}, last {minutes} min "
        "(most frequent first):"
    ]
    for group in ranked[:limit]:
        times = [e[0] for e in group]
        newest = max(group)
        lines.append(
            f"\n{len(group)}× [{newest[1]}] between {clock(min(times))} and {clock(max(times))}\n"
            f"   example: {newest[2][:MAX_LINE]}"
        )
    if len(ranked) > limit:
        rest = sum(len(g) for g in ranked[limit:])
        lines.append(f"\n… and {len(ranked) - limit} more patterns ({rest} lines): filter more")
    return "\n".join(lines)
