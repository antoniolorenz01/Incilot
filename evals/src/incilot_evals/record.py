"""Records complete investigations for the demo, with everything needed to replay them.

    python -m incilot_evals.record [scenario/variant ...] [--force]
    make record                                   # every variant in the catalogue
    make record ARGS="deploy-memory-leak/shop-recent-orders"

For each one: break the shop, let the agent investigate, approve its proposal (as a
visitor would), wait for the verification and save to web/public/replays/:

- every event of the investigation, with the moment it was published;
- the shop's health metrics (the same series as the "Shop health" charts), from 15
  minutes before the fault until the shop has recovered;
- when the fault was injected, the right answer, and the model that investigated.

Only resolved incidents are saved. Variants already recorded are skipped (--force
records them again), so a run cut short picks up where it stopped.
"""

import argparse
import json
import os
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

INJECTOR = os.getenv("INJECTOR_URL", "http://localhost:8100")
AGENT = os.getenv("AGENT_API_URL", "http://localhost:8200")
PROMETHEUS = os.getenv("PROMETHEUS_URL", "http://localhost:9090")
OUT = Path("web/public/replays")
ALERT = "Shop degraded since {since:%H:%M:%S} UTC: customers are complaining."
WARMUP_SECONDS = 60
SETTLE_SECONDS = 30  # after the verification, so the charts show the shop back to normal
HISTORY_MINUTES = 15  # of normal shop before the fault, as the live charts show
TIMEOUT_SECONDS = 900
TRUTH = ("scenario", "variant", "service", "root_cause", "action", "culprit_sha", "decoy_shas")
# The "Shop health" charts: the same queries as web/src/app/api/health/route.ts.
HEALTH = {
    "orders": 'sum(rate(orders_total{status="confirmed"}[1m])) * 60',
    "errors": 'sum(rate(http_requests_total{service="shop",status=~"5.."}[1m]))'
    ' / sum(rate(http_requests_total{service="shop"}[1m])) * 100',
    "latency": "histogram_quantile(0.95, sum by (le) "
    '(rate(http_request_duration_seconds_bucket{service="shop"}[1m]))) * 1000',
}


def follow(agent: httpx.Client, investigation_id: str, events: list, until: str) -> dict | None:
    """Reads the event stream (resuming after the last event kept) until `until` arrives.
    Returns that event, or the error event."""
    deadline = time.monotonic() + TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        headers = {"last-event-id": events[-1]["id"]} if events else {}
        url = f"/investigations/{investigation_id}/events"
        try:
            with agent.stream("GET", url, headers=headers, timeout=TIMEOUT_SECONDS) as response:
                event_id = None
                for line in response.iter_lines():
                    if line.startswith("id: "):
                        event_id = line.removeprefix("id: ")
                    elif line.startswith("data: ") and event_id:
                        event = json.loads(line.removeprefix("data: "))
                        # The stream id is "<ms>-<n>": when it was published.
                        events.append({"id": event_id, "at": int(event_id.split("-")[0]), **event})
                        if event["type"] in (until, "error"):
                            return event
        except httpx.TransportError:
            time.sleep(2)
    return None


def health(start: datetime, end: datetime) -> dict[str, list[list[float]]]:
    """Each chart's series: [[unix ms, value], …] every 15 s."""
    series = {}
    with httpx.Client(base_url=PROMETHEUS, timeout=30) as prometheus:
        for key, query in HEALTH.items():
            window = {"start": start.timestamp(), "end": end.timestamp(), "step": 15}
            params = {"query": query, **window}
            body = prometheus.get("/api/v1/query_range", params=params).json()
            result = body.get("data", {}).get("result", [])
            values = result[0]["values"] if result else []
            series[key] = [[int(t * 1000), _number(v)] for t, v in values]
    return series


def _number(value: str) -> float:
    number = float(value)
    return number if number == number and abs(number) != float("inf") else 0.0


def model() -> str:
    """Which model investigated, from the .env the agent runs with."""
    env = {}
    if Path(".env").exists():
        for line in Path(".env").read_text().splitlines():
            key, _, value = line.partition("=")
            env[key.strip()] = value.strip()
    if env.get("LLM_PROVIDER") == "claude-code":
        return f"Claude {env.get('CLAUDE_CODE_MODEL', 'sonnet').capitalize()} (via Claude Code)"
    return env.get("OPENAI_MODEL", "unknown")


def path_for(scenario: str, variant: str) -> Path:
    return OUT / f"{scenario}--{variant}.json"


def record(injector: httpx.Client, agent: httpx.Client, scenario: str, variant: str) -> Path | None:
    injected = injector.post("/injections", json={"scenario": scenario, "variant": variant})
    injected.raise_for_status()
    since = datetime.fromisoformat(injected.json()["injected_at"])
    try:
        time.sleep(WARMUP_SECONDS)
        started = agent.post(
            "/investigations",
            json={"alert": ALERT.format(since=since), "since": since.isoformat()},
        )
        started.raise_for_status()
        investigation_id = started.json()["id"]
        events: list[dict] = []
        reached = follow(agent, investigation_id, events, "awaiting_approval")
        if not reached or reached["type"] == "error":
            # The agent itself failed (no model, no bridge…): the next ones would too.
            error = reached.get("error") if reached else "timed out"
            hint = " (is `make claude-bridge` running?)" if "Connect" in str(error) else ""
            raise SystemExit(f"the agent failed: {error}{hint}")
        truth = {k: v for k, v in injector.get("/injections/active").json().items() if k in TRUTH}
        agent.post(
            f"/investigations/{investigation_id}/approval",
            json={"approved": True, "note": "recorded for the demo"},
        ).raise_for_status()
        last = follow(agent, investigation_id, events, "done")
    finally:
        if injector.get("/injections/active").status_code == 200:
            injector.post("/injections/active/recover")

    verification = next((e for e in events if e["type"] == "verification"), {})
    if not last or last["type"] != "done" or not verification.get("recovered"):
        print("      not saved: the shop did not recover")
        return None
    time.sleep(SETTLE_SECONDS)
    metrics = health(since - timedelta(minutes=HISTORY_MINUTES), datetime.now(UTC))
    path = path_for(scenario, variant)
    path.write_text(
        json.dumps(
            {
                "scenario": scenario,
                "variant": variant,
                "model": model(),
                "recordedAt": datetime.now(UTC).isoformat(timespec="seconds"),
                "injectedAt": int(since.timestamp() * 1000),
                "truth": truth,
                "events": [{k: v for k, v in e.items() if k != "id"} for e in events],
                "health": metrics,
            },
            indent=1,
            ensure_ascii=False,
        )
    )
    return path


def write_index(catalog: dict) -> None:
    """index.json: what the page lists, in a fixed order."""
    order = {"deploy": 0, "config": 1, "infra": 2, "external": 3}
    items = []
    for path in sorted(OUT.glob("*--*.json")):
        replay = json.loads(path.read_text())
        spec = catalog.get(replay["scenario"], {})
        items.append(
            {
                "file": path.name,
                "scenario": replay["scenario"],
                "variant": replay["variant"],
                "title": spec.get("title", replay["scenario"]),
                "category": spec.get("category", ""),
                "recordedAt": replay["recordedAt"],
            }
        )
    items.sort(key=lambda i: (order.get(i["category"], 9), i["title"], i["variant"]))
    (OUT / "index.json").write_text(json.dumps(items, indent=1, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(description="Record investigations for the demo")
    parser.add_argument("items", nargs="*", help="scenario/variant (default: all of them)")
    parser.add_argument("--force", action="store_true", help="record again what already exists")
    args = parser.parse_args()

    injector = httpx.Client(base_url=INJECTOR, timeout=60)
    agent = httpx.Client(base_url=AGENT, timeout=30)
    if injector.get("/injections/active").status_code != 404:
        raise SystemExit("an injection is active: recover it first (make injector ARGS=recover)")
    OUT.mkdir(parents=True, exist_ok=True)
    catalog = injector.get("/scenarios").json()
    every = [f"{s}/{v['variant']}" for s, spec in sorted(catalog.items()) for v in spec["variants"]]
    items = args.items or every
    todo = [i for i in items if args.force or not path_for(*i.split("/")).exists()]
    print(f"{len(todo)} to record ({len(items) - len(todo)} already done) · ~{len(todo) * 4} min")
    print(f"model: {model()}")
    for index, item in enumerate(todo, start=1):
        print(f"[{index}/{len(todo)}] {item} …", flush=True)
        if path := record(injector, agent, *item.split("/")):
            print(f"      saved {path}")
        write_index(catalog)
        time.sleep(30)  # let the shop return to normal before the next one


if __name__ == "__main__":
    main()
