"""Runs the fault catalogue and grades the agent against the ground truth.

    python -m incilot_evals.run [--scenario ID ...] [--split dev|exam|all] [--limit N]
    make eval ARGS="--split dev --limit 5"

For each variant: inject → wait for symptoms → start an investigation through the
agent's API (the real path: API → queue → worker) → wait for the diagnosis → grade it
against the ground truth → recover → wait for the shop to return to normal.

The evaluator runs outside the agent: it reads the ground truth from the injector only
after the agent has given its diagnosis. Each variant costs one real investigation (tokens).
"""

import argparse
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

from incilot_evals.scoring import score

INJECTOR = os.getenv("INJECTOR_URL", "http://localhost:8100")
AGENT = os.getenv("AGENT_API_URL", "http://localhost:8200")
# Like a real alert, it says since when. Without the time, the agent mixed leftovers from
# the previous scenario (its logs are still in the search window) with the current incident.
ALERT = "[eval] Shop degraded since {since:%H:%M:%S} UTC: customers are complaining."
INVESTIGATION_TIMEOUT = 600
# Difficulty per incident type (see TONI-82).
DIFFICULTY = {
    "infra-service-down": "easy",
    "infra-redis-down": "easy",
    "config-broken-upstream-url": "easy",
    "deploy-latency-regression": "medium",
    "deploy-intermittent-errors": "medium",
    "config-rate-limit": "medium",
    "config-payment-declines": "medium",
    "external-provider-slow": "medium",
    "deploy-stuck-migration": "medium",
    "deploy-reservation-leak": "hard",
    "config-cache-ttl-zero": "hard",
    "deploy-memory-leak": "hard",
    "deploy-db-connection-leak": "hard",
}


def variants(scenario_ids: list[str] | None, split: str) -> list[dict]:
    catalog = httpx.get(f"{INJECTOR}/scenarios", timeout=10).json()
    return [
        {"scenario": scenario, "variant": v["variant"], "split": v["split"]}
        for scenario, spec in sorted(catalog.items())
        if not scenario_ids or scenario in scenario_ids
        for v in spec["variants"]
        if split == "all" or v["split"] == split
    ]


def investigate(client: httpx.Client, since: datetime) -> dict:
    """Starts an investigation and follows its events until the diagnosis.

    If the stream drops, it reconnects: the API replays the history from the start.
    """
    alert = ALERT.format(since=since)
    request = {"alert": alert, "since": since.isoformat()}
    started = client.post("/investigations", json=request)
    if started.status_code != 202:
        error = f"the agent API returned {started.status_code}: {started.text[:200]}"
        return {"id": None, "rounds": 0, "diagnosis": None, "error": error}
    investigation_id = started.json()["id"]
    result = {"id": investigation_id, "rounds": 0, "diagnosis": None, "error": None}
    url = f"/investigations/{investigation_id}/events"
    deadline = time.monotonic() + INVESTIGATION_TIMEOUT
    while time.monotonic() < deadline:
        try:
            with client.stream("GET", url, timeout=INVESTIGATION_TIMEOUT) as response:
                for line in response.iter_lines():
                    if not line.startswith("data: "):
                        continue
                    event = json.loads(line.removeprefix("data: "))
                    if event["type"] == "tool_call":
                        result["rounds"] = max(result["rounds"], event["round"])
                    elif event["type"] == "diagnosis":
                        result |= {"diagnosis": event["diagnosis"], "tokens": event["tokens"],
                                   "stop_reason": event["stop_reason"]}  # fmt: skip
                    elif event["type"] == "error":
                        return result | {"error": event["error"]}
                    elif event["type"] == "awaiting_approval":
                        return result
        except httpx.TransportError as exc:
            print(f"      (stream dropped: {type(exc).__name__}; reconnecting)", flush=True)
            time.sleep(2)
    return result | {"error": "timed out waiting for the diagnosis"}


def run_one(item: dict, warmup: int, cooldown: int) -> dict:
    injector = httpx.Client(base_url=INJECTOR, timeout=60)
    agent = httpx.Client(base_url=AGENT, timeout=30)
    started = time.monotonic()
    injector.post("/injections", json={"scenario": item["scenario"], "variant": item["variant"]})
    since = datetime.now(UTC)
    try:
        time.sleep(warmup)
        investigated = time.monotonic()
        outcome = investigate(agent, since)
        elapsed = time.monotonic() - investigated
        truth = injector.get("/injections/active").json()  # only now: after the diagnosis
        if outcome["id"]:  # close the investigation without executing anything
            agent.post(
                f"/investigations/{outcome['id']}/approval",
                json={"approved": False, "note": "eval: not executed"},
            )
    finally:
        injector.post("/injections/active/recover")
    time.sleep(cooldown)

    grades = (
        score(truth, outcome["diagnosis"])
        if outcome["diagnosis"]
        else {"action_ok": False, "service_ok": False, "commit": "missing", "commit_ok": False}
    )
    return (
        item
        | grades
        | {
            "difficulty": DIFFICULTY.get(item["scenario"], "?"),
            "rounds": outcome["rounds"],
            "tokens": outcome.get("tokens", 0),
            "seconds": round(elapsed),
            "total_seconds": round(time.monotonic() - started),
            "error": outcome["error"],
            "diagnosis": outcome["diagnosis"],
            "truth": {
                k: truth.get(k)
                for k in ("service", "action", "culprit_sha", "decoy_shas", "root_cause")
            },
        }
    )


def mark(ok: bool) -> str:
    return "✅" if ok else "❌"


def pct(results: list[dict], key: str) -> str:
    return f"{sum(r[key] for r in results) / len(results):.0%}" if results else "—"


def print_report(results: list[dict]) -> None:
    print(f"\n{'scenario/variant':52} {'action':>6} {'service':>8} {'commit':>15} "
          f"{'rounds':>6} {'tokens':>7}")  # fmt: skip
    for r in results:
        name = f"{r['scenario']}/{r['variant']}"
        action, service = mark(r["action_ok"]), mark(r["service_ok"])
        print(
            f"{name[:52]:52} {action:>5} {service:>7}"
            f" {r['commit']:>15} {r['rounds']:>6} {r['tokens']:>7}"
        )
    header = f"{'group':12} {'n':>3} {'action ✓':>9} {'service':>9} {'commit':>7}"
    print(f"\n{header} {'avg tokens':>13}")
    groups = {"total": results}
    for key in ("split", "difficulty"):
        for value in sorted({r[key] for r in results}):
            groups[value] = [r for r in results if r[key] == value]
    for name, rs in groups.items():
        tokens = sum(r["tokens"] for r in rs) // len(rs) if rs else 0
        print(f"{name:12} {len(rs):>3} {pct(rs, 'action_ok'):>9} {pct(rs, 'service_ok'):>9} "
              f"{pct(rs, 'commit_ok'):>7} {tokens:>13}")  # fmt: skip
    total_tokens = sum(r["tokens"] for r in results)
    decoys = sum(r["commit"] in ("decoy", "blamed_innocent") for r in results)
    print(f"\nblamed an innocent commit: {decoys} · total tokens: {total_tokens}")
    if price := os.getenv("EVAL_USD_PER_MTOKENS"):
        print(f"estimated cost: US$ {total_tokens / 1e6 * float(price):.2f}")


def main() -> None:
    parser = argparse.ArgumentParser(description="IncidentPilot evals")
    parser.add_argument("--scenario", action="append", help="only these scenarios")
    parser.add_argument("--split", default="all", choices=["dev", "exam", "all"])
    parser.add_argument("--limit", type=int, help="at most N variants")
    parser.add_argument("--warmup", type=int, default=60, help="seconds for symptoms to appear")
    parser.add_argument("--cooldown", type=int, default=30, help="seconds to return to normal")
    args = parser.parse_args()

    if httpx.get(f"{INJECTOR}/injections/active", timeout=10).status_code != 404:
        raise SystemExit("an injection is active: recover it first (make injector ARGS=recover)")
    items = variants(args.scenario, args.split)[: args.limit]
    minutes = len(items) * (args.warmup + args.cooldown + 120) / 60
    print(f"{len(items)} variants · ~{minutes:.0f} min · one real investigation per variant")

    results = []
    for index, item in enumerate(items, start=1):
        print(f"[{index}/{len(items)}] {item['scenario']}/{item['variant']} …", flush=True)
        results.append(run_one(item, args.warmup, args.cooldown))
        r = results[-1]
        grades = f"action {mark(r['action_ok'])} · service {mark(r['service_ok'])}"
        print(f"      {grades} · commit {r['commit']} · {r['tokens']} tokens · {r['seconds']} s")

    print_report(results)
    out = Path("build/evals") / f"{datetime.now(UTC):%Y%m%d-%H%M%S}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2, ensure_ascii=False, default=str))
    print(f"full report: {out}")


if __name__ == "__main__":
    main()
