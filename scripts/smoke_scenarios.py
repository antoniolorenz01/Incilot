"""Smoke test del catálogo de fallos: inyecta cada escenario, mide su síntoma y recupera.

    make smoke                      # todos (~1 min por escenario)
    make smoke ARGS="config-rate-limit infra-service-down"

Necesita el entorno levantado (`make up`) y ninguna inyección activa. Usa solo la
API del injector (localhost:8100), Prometheus (9090) y Loki (3100).
"""

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

INJECTOR = "http://localhost:8100"
PROMETHEUS = "http://localhost:9090"
LOKI = "http://localhost:3100"
WAIT_INJECTED = 30
WAIT_RECOVERED = 30


def http(method: str, url: str, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data, {"content-type": "application/json"}, method=method)
    with urllib.request.urlopen(request) as response:
        return json.load(response)


def prom(query: str) -> float:
    url = f"{PROMETHEUS}/api/v1/query?" + urllib.parse.urlencode({"query": query})
    result = http("GET", url)["data"]["result"]
    return float(result[0]["value"][1]) if result else 0.0


def loki(query: str) -> float:
    url = f"{LOKI}/loki/api/v1/query?" + urllib.parse.urlencode({"query": query})
    result = http("GET", url)["data"]["result"]
    return float(result[0]["value"][1]) if result else 0.0


def rate(selector: str) -> str:
    return f"sum(rate({selector}[20s])) or vector(0)"


def p95(selector: str) -> str:
    return f"histogram_quantile(0.95, sum by (le) (rate({selector}[20s])))"


# escenario: (variante, qué se mide, cómo medirlo, ¿hay síntoma?, ¿se recuperó?)
CHECKS = {
    "deploy-latency-regression": (
        "inventory-stock-recount",
        "p95 shop→inventory (s)",
        lambda: prom(
            p95('upstream_request_duration_seconds_bucket{service="shop",target="inventory"}')
        ),
        lambda before, during: during > 0.3,
        lambda before, after: after < 0.1,
    ),
    "deploy-intermittent-errors": (
        "users-tier-labels",
        "500/s en users",
        lambda: prom(rate('http_requests_total{service="users",status="500"}')),
        lambda before, during: during > 0.1,
        lambda before, after: after < 0.05,
    ),
    "deploy-reservation-leak": (
        "shop-declined-refactor",
        "'reservation released' en 30 s",
        lambda: loki('sum(count_over_time({service="inventory"} |= "reservation released" [30s]))'),
        lambda before, during: during == 0,
        None,  # depende de que haya rechazos de pago en la ventana: no se exige
    ),
    "deploy-memory-leak": (
        "shop-recent-orders",
        "memoria de shop (MB)",
        lambda: prom('process_resident_memory_bytes{service="shop"}') / 1e6,
        lambda before, during: during > before + 50,
        lambda before, after: after < before + 30,
    ),
    "deploy-db-connection-leak": (
        "inventory-release-connection",
        "timeouts/s shop→inventory",
        lambda: prom(
            rate('upstream_requests_total{service="shop",target="inventory",status="timeout"}')
        ),
        lambda before, during: during > 0.2,
        lambda before, after: after < 0.05,
    ),
    "deploy-stuck-migration": (
        "products-add-column",
        "timeouts/s shop→inventory",
        lambda: prom(
            rate('upstream_requests_total{service="shop",target="inventory",status="timeout"}')
        ),
        lambda before, during: during > 0.2,
        lambda before, after: after < 0.05,
    ),
    "config-payment-declines": (
        "strict-fraud-check",
        "pedidos rechazados/s",
        lambda: prom(rate('orders_total{reason="payment_declined"}')),
        lambda before, during: during > 0.5,
        lambda before, after: after < 0.3,
    ),
    "config-rate-limit": (
        "payments-per-replica",
        "429/s en payments",
        lambda: prom(rate('http_requests_total{service="payments",status="429"}')),
        lambda before, during: during > 0.2,
        lambda before, after: after < 0.05,
    ),
    "config-cache-ttl-zero": (
        "users-ttl-zero",
        "p95 users (s)",
        lambda: prom(p95('http_request_duration_seconds_bucket{service="users"}')),
        lambda before, during: during > before + 0.03,
        lambda before, after: after < before + 0.02,
    ),
    "config-broken-upstream-url": (
        "inventory-url-typo",
        "errores/s shop→inventory",
        lambda: prom(
            rate('upstream_requests_total{service="shop",target="inventory",status="error"}')
        ),
        lambda before, during: during > 0.2,
        lambda before, after: after < 0.05,
    ),
    "external-provider-slow": (
        "provider-timeouts",
        "timeouts/s shop→payments",
        lambda: prom(
            rate('upstream_requests_total{service="shop",target="payments",status="timeout"}')
        ),
        lambda before, during: during > 0.2,
        lambda before, after: after < 0.05,
    ),
    "infra-redis-down": (
        "redis-stopped",
        "500/s en shop",
        lambda: prom(rate('http_requests_total{service="shop",status="500"}')),
        lambda before, during: during > 1,
        lambda before, after: after < 0.1,
    ),
    "infra-service-down": (
        "payments-down",
        "pedidos payments_unavailable/s",
        lambda: prom(rate('orders_total{reason="payments_unavailable"}')),
        lambda before, during: during > 0.2,
        lambda before, after: after < 0.05,
    ),
}


def run(scenario: str) -> bool:
    variant, label, measure, has_symptom, recovered = CHECKS[scenario]
    before = measure()
    http("POST", f"{INJECTOR}/injections", {"scenario": scenario, "variant": variant})
    try:
        time.sleep(WAIT_INJECTED)
        during = measure()
    finally:
        http("POST", f"{INJECTOR}/injections/active/recover")
    time.sleep(WAIT_RECOVERED)
    after = measure()

    ok = has_symptom(before, during) and (recovered is None or recovered(before, after))
    print(
        f"{'OK   ' if ok else 'FALLA'} {scenario:28} {label:32} "
        f"antes {before:8.2f} → con fallo {during:8.2f} → después {after:8.2f}",
        flush=True,
    )
    return ok


def main() -> None:
    scenarios = sys.argv[1:] or list(CHECKS)
    try:
        http("GET", f"{INJECTOR}/injections/active")
        sys.exit("hay una inyección activa: recuperala antes (make injector ARGS=recover)")
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise
    results = [run(s) for s in scenarios]
    print(f"\n{sum(results)}/{len(results)} escenarios OK")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
