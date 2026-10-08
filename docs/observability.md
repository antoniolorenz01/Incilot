# Observability

| Tool | URL | What it stores |
|---|---|---|
| Prometheus | http://localhost:9090 | Metrics, scraped every 5 s |
| Loki | http://localhost:3100 | Logs from every container |
| Grafana | http://localhost:3000 | UI over Prometheus and Loki (no login) |

## Logs

Each service writes one JSON line per event to stdout. Alloy collects the logs of
containers labelled `incilot.logs=true` and ships them to Loki.

```json
{"ts": "2026-10-02T06:52:43.194+00:00", "level": "info", "service": "shop",
 "logger": "incilot_sim.services.shop", "msg": "order confirmed",
 "request_id": "854e6e9cfe85405b9ceb7fb9069ee45c", "order_id": "…", "amount_cents": 8900}
```

| Field | Meaning |
|---|---|
| `ts` | UTC timestamp |
| `level` | `info`, `warning`, `error` |
| `service` | Service that wrote the log |
| `logger` | Source module (`http` = access log) |
| `msg` | Event. Fixed, searchable text |
| `request_id` | Request identifier; propagated between services in the `x-request-id` header |
| `exc` | Traceback, only for unhandled errors |
| everything else | Event-specific fields (`order_id`, `reason`, `target`…) |

**Access log**: every request (except `/health` and `/metrics`) produces a log
with `msg: "request"` and `method`, `path`, `status` and `duration_ms`. Its level
depends on the status: `info` (< 400), `warning` (4xx), `error` (5xx).

**Loki labels**: `service` and `level`. Everything else is filtered with `| json`.

```logql
{service="shop", level="error"}                                  # shop errors
{service=~".+"} |= "854e6e9cfe85405b9ceb7fb9069ee45c"            # one request across every service
{service="shop"} | json | msg="order failed" | reason="out_of_stock"
sum by (service) (count_over_time({level="error"}[5m]))          # errors per service
```

Postgres and Redis also ship their logs to Loki (`service="postgres"`,
`service="redis"`), in their native text format.

## Metrics

All of them carry the `service` label, which Prometheus adds when scraping.

| Metric | Type | Labels | What it measures |
|---|---|---|---|
| `http_requests_total` | counter | `method`, `route`, `status` | Requests served |
| `http_request_duration_seconds` | histogram | `method`, `route` | Latency of requests served |
| `upstream_requests_total` | counter | `target`, `status` | Calls to other services. `status` is the HTTP code, `timeout` or `error` (connection failed) |
| `upstream_request_duration_seconds` | histogram | `target` | Latency of calls to other services |
| `orders_total` | counter | `status`, `reason` | Orders by outcome (`shop` only, see [shop.md](services/shop.md)) |

`route` is the route template (`/users/{user_id}`), not the concrete URL.

```promql
# Throughput per service
sum by (service) (rate(http_requests_total[1m]))

# 5xx error rate per service
sum by (service) (rate(http_requests_total{status=~"5.."}[5m]))
  / sum by (service) (rate(http_requests_total[5m]))

# p95 latency per service and route
histogram_quantile(0.95, sum by (service, route, le) (rate(http_request_duration_seconds_bucket[5m])))

# p95 latency from shop to each dependency
histogram_quantile(0.95, sum by (target, le) (rate(upstream_request_duration_seconds_bucket[5m])))

# Orders by outcome
sum by (status, reason) (rate(orders_total[5m]))
```
