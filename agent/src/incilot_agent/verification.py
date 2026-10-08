"""Verification (did the shop recover?) and a record of each incident.

After executing the approved action it waits for the metrics to reflect the change and
checks the shop's health indicators. Each incident is recorded in agent_state
(diagnosis, human decision, action, execution and verification): it feeds the evals
and the incident memory.
"""

import asyncio
import json
import os

import asyncpg
import httpx

from incilot_agent import config

VERIFY_WAIT_SECONDS = int(os.getenv("AGENT_VERIFY_SECONDS", "60"))
# (name, PromQL, maximum threshold): the shop is healthy if all stay below.
HEALTH_CHECKS = [
    (
        "shop 5xx errors",
        'sum(rate(http_requests_total{service="shop",status=~"5.."}[1m]))'
        ' / sum(rate(http_requests_total{service="shop"}[1m]))',
        0.05,
    ),
    (
        "shop p95 (s)",
        "histogram_quantile(0.95, sum by (le) "
        '(rate(http_request_duration_seconds_bucket{service="shop"}[1m])))',
        0.5,
    ),
    (
        "failed orders",
        'sum(rate(orders_total{status="failed"}[1m])) / sum(rate(orders_total[1m]))',
        0.10,
    ),
]


class PrometheusVerifier:
    def __init__(self, wait_seconds: int = VERIFY_WAIT_SECONDS):
        self.wait_seconds = wait_seconds

    async def verify(self) -> dict:
        await asyncio.sleep(self.wait_seconds)  # let the metrics reflect the action
        checks = []
        async with httpx.AsyncClient(base_url=config.PROMETHEUS_URL, timeout=10) as http:
            for name, query, threshold in HEALTH_CHECKS:
                result = (await http.get("/api/v1/query", params={"query": query})).json()
                series = result["data"]["result"]
                value = float(series[0]["value"][1]) if series else 0.0
                value = 0.0 if value != value else value  # NaN (no traffic) → 0
                checks.append(
                    {
                        "name": name,
                        "value": round(value, 4),
                        "max": threshold,
                        "ok": value <= threshold,
                    }
                )
        return {"recovered": all(c["ok"] for c in checks), "checks": checks}


SCHEMA = """
CREATE TABLE IF NOT EXISTS incidents (
    id TEXT PRIMARY KEY,
    alert TEXT,
    diagnosis JSONB,
    approval JSONB,
    action JSONB,
    execution JSONB,
    verification JSONB,
    tokens INTEGER,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


class PostgresRecorder:
    async def record(self, incident_id: str, state: dict) -> None:
        conn = await asyncpg.connect(config.AGENT_STATE_URL)
        try:
            await conn.execute(SCHEMA)
            await conn.execute(
                "INSERT INTO incidents (id, alert, diagnosis, approval, action, execution, "
                "verification, tokens) VALUES ($1, $2, $3, $4, $5, $6, $7, $8) "
                "ON CONFLICT (id) DO UPDATE SET approval = $4, action = $5, execution = $6, "
                "verification = $7, recorded_at = now()",
                incident_id,
                state.get("alert"),
                *(
                    json.dumps(state.get(key))
                    for key in (
                        "diagnosis",
                        "approval",
                        "approved_action",
                        "execution",
                        "verification",
                    )
                ),
                state.get("tokens", 0),
            )
        finally:
            await conn.close()


class NullVerifier:
    async def verify(self) -> dict:
        return {"recovered": False, "checks": [], "skipped": True}


class NullRecorder:
    async def record(self, incident_id: str, state: dict) -> None:
        return None
