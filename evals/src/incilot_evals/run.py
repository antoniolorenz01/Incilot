"""Corre el catálogo de fallos y corrige al agente contra el ground truth.

    python -m incilot_evals.run [--scenario ID ...] [--split dev|exam|all] [--limit N]
    make eval ARGS="--split dev --limit 5"

Por cada variante: inyecta → espera los síntomas → lanza una investigación por la API
del agente (el camino real: API → cola → worker) → espera el diagnóstico → lo corrige
contra el ground truth → recupera → espera a que la tienda se normalice.

El evaluador corre fuera del agente: lee el ground truth del injector solo después de que
el agente diagnosticó. Cuesta una investigación real (tokens) por variante.
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
# Como una alerta real: dice desde cuándo. Sin la hora, el agente mezclaba restos del
# escenario anterior (sus logs siguen en la ventana de búsqueda) con el incidente actual.
ALERT = "[eval] Degradación en la tienda desde las {since} UTC: hay quejas de clientes."
INVESTIGATION_TIMEOUT = 600
# Dificultad por tipo de incidente (ver TONI-82).
DIFFICULTY = {
    "infra-service-down": "fácil",
    "infra-redis-down": "fácil",
    "config-broken-upstream-url": "fácil",
    "deploy-latency-regression": "media",
    "deploy-intermittent-errors": "media",
    "config-rate-limit": "media",
    "config-payment-declines": "media",
    "external-provider-slow": "media",
    "deploy-stuck-migration": "media",
    "deploy-reservation-leak": "difícil",
    "config-cache-ttl-zero": "difícil",
    "deploy-memory-leak": "difícil",
    "deploy-db-connection-leak": "difícil",
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


def investigate(client: httpx.Client, since: str) -> dict:
    """Lanza una investigación y sigue sus eventos hasta el diagnóstico.

    Si el streaming se corta, se reconecta: la API reenvía la historia desde el principio.
    """
    alert = ALERT.format(since=since)
    investigation_id = client.post("/investigations", json={"alert": alert}).json()["id"]
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
            print(f"      (streaming cortado: {type(exc).__name__}; reconectando)", flush=True)
            time.sleep(2)
    return result | {"error": "timeout esperando el diagnóstico"}


def run_one(item: dict, warmup: int, cooldown: int) -> dict:
    injector = httpx.Client(base_url=INJECTOR, timeout=60)
    agent = httpx.Client(base_url=AGENT, timeout=30)
    started = time.monotonic()
    injector.post("/injections", json={"scenario": item["scenario"], "variant": item["variant"]})
    since = datetime.now(UTC).strftime("%H:%M")
    try:
        time.sleep(warmup)
        investigated = time.monotonic()
        outcome = investigate(agent, since)
        elapsed = time.monotonic() - investigated
        truth = injector.get("/injections/active").json()  # recién ahora: después del diagnóstico
        if outcome["id"]:  # cerrar la investigación sin ejecutar nada
            agent.post(
                f"/investigations/{outcome['id']}/approval",
                json={"approved": False, "note": "eval: no se ejecuta"},
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
    print(f"\n{'escenario/variante':52} {'acción':>6} {'servicio':>8} {'commit':>15} "
          f"{'rondas':>6} {'tokens':>7}")  # fmt: skip
    for r in results:
        name = f"{r['scenario']}/{r['variant']}"
        action, service = mark(r["action_ok"]), mark(r["service_ok"])
        print(
            f"{name[:52]:52} {action:>5} {service:>7}"
            f" {r['commit']:>15} {r['rounds']:>6} {r['tokens']:>7}"
        )
    header = f"{'grupo':12} {'n':>3} {'acción ✓':>9} {'servicio':>9} {'commit':>7}"
    print(f"\n{header} {'tokens prom.':>13}")
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
    print(f"\nculpó a un commit inocente: {decoys} · tokens totales: {total_tokens}")
    if price := os.getenv("EVAL_USD_PER_MTOKENS"):
        print(f"costo estimado: US$ {total_tokens / 1e6 * float(price):.2f}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Evals de IncidentPilot")
    parser.add_argument("--scenario", action="append", help="limitar a estos escenarios")
    parser.add_argument("--split", default="all", choices=["dev", "exam", "all"])
    parser.add_argument("--limit", type=int, help="como mucho N variantes")
    parser.add_argument(
        "--warmup", type=int, default=60, help="segundos para que aparezcan síntomas"
    )
    parser.add_argument("--cooldown", type=int, default=30, help="segundos para que se normalice")
    args = parser.parse_args()

    if httpx.get(f"{INJECTOR}/injections/active", timeout=10).status_code != 404:
        raise SystemExit("hay una inyección activa: recuperala antes (make injector ARGS=recover)")
    items = variants(args.scenario, args.split)[: args.limit]
    minutes = len(items) * (args.warmup + args.cooldown + 120) / 60
    print(f"{len(items)} variantes · ~{minutes:.0f} min · una investigación real por variante")

    results = []
    for index, item in enumerate(items, start=1):
        print(f"[{index}/{len(items)}] {item['scenario']}/{item['variant']} …", flush=True)
        results.append(run_one(item, args.warmup, args.cooldown))
        r = results[-1]
        grades = f"acción {mark(r['action_ok'])} · servicio {mark(r['service_ok'])}"
        print(f"      {grades} · commit {r['commit']} · {r['tokens']} tokens · {r['seconds']} s")

    print_report(results)
    out = Path("build/evals") / f"{datetime.now(UTC):%Y%m%d-%H%M%S}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2, ensure_ascii=False, default=str))
    print(f"reporte completo: {out}")


if __name__ == "__main__":
    main()
