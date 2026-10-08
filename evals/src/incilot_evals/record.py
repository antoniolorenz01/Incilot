"""Records complete investigations for the public demo's replays.

    python -m incilot_evals.record [scenario/variant ...]
    make record                                   # the default set, one per category
    make record ARGS="deploy-memory-leak/shop-recent-orders"

For each one: break the shop, let the agent investigate, approve its proposal (as a
visitor would), wait for the verification and save every event, with the moment it
was published, to web/public/replays/<scenario>.json. Only resolved incidents are
saved. Replays cost nothing to watch and work even when the shop is busy or down.
"""

import argparse
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

INJECTOR = os.getenv("INJECTOR_URL", "http://localhost:8100")
AGENT = os.getenv("AGENT_API_URL", "http://localhost:8200")
OUT = Path("web/public/replays")
ALERT = "Shop degraded since {since:%H:%M:%S} UTC: customers are complaining."
WARMUP_SECONDS = 60
TIMEOUT_SECONDS = 900
# One per kind of fault, chosen to be easy to follow for someone outside the field.
DEFAULT = [
    "deploy-intermittent-errors/users-tier-labels",
    "config-payment-declines/strict-fraud-check",
    "infra-service-down/payments-down",
    "external-provider-slow/provider-timeouts",
]
TRUTH = ("scenario", "variant", "service", "root_cause", "action", "culprit_sha", "decoy_shas")


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
    path = OUT / f"{scenario}.json"
    path.write_text(
        json.dumps(
            {
                "scenario": scenario,
                "variant": variant,
                "recordedAt": datetime.now(UTC).isoformat(timespec="seconds"),
                "truth": truth,
                "events": [{k: v for k, v in e.items() if k != "id"} for e in events],
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
    for path in sorted(OUT.glob("*.json")):
        if path.name == "index.json":
            continue
        replay = json.loads(path.read_text())
        spec = catalog.get(replay["scenario"], {})
        items.append(
            {
                "file": path.name,
                "title": spec.get("title", replay["scenario"]),
                "category": spec.get("category", ""),
                "recordedAt": replay["recordedAt"],
            }
        )
    items.sort(key=lambda i: (order.get(i["category"], 9), i["title"]))
    (OUT / "index.json").write_text(json.dumps(items, indent=1, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(description="Record investigations for the demo's replays")
    parser.add_argument("items", nargs="*", default=DEFAULT, help="scenario/variant")
    args = parser.parse_args()

    injector = httpx.Client(base_url=INJECTOR, timeout=60)
    agent = httpx.Client(base_url=AGENT, timeout=30)
    if injector.get("/injections/active").status_code != 404:
        raise SystemExit("an injection is active: recover it first (make injector ARGS=recover)")
    OUT.mkdir(parents=True, exist_ok=True)
    catalog = injector.get("/scenarios").json()
    for index, item in enumerate(args.items, start=1):
        scenario, variant = item.split("/")
        print(f"[{index}/{len(args.items)}] {item} …", flush=True)
        if path := record(injector, agent, scenario, variant):
            print(f"      saved {path}")
        time.sleep(30)  # let the shop return to normal before the next one
    write_index(catalog)


if __name__ == "__main__":
    main()
