# Observabilidad

| Herramienta | URL | Qué guarda |
|---|---|---|
| Prometheus | http://localhost:9090 | Métricas, scrapeadas cada 5 s |
| Loki | http://localhost:3100 | Logs de todos los contenedores |
| Grafana | http://localhost:3000 | UI sobre Prometheus y Loki (sin login) |

## Logs

Cada servicio escribe una línea JSON por evento a stdout. Alloy recoge los logs de
los contenedores con la etiqueta `incilot.logs=true` y los envía a Loki.

```json
{"ts": "2026-10-02T06:52:43.194+00:00", "level": "info", "service": "shop",
 "logger": "incilot_sim.services.shop", "msg": "order confirmed",
 "request_id": "854e6e9cfe85405b9ceb7fb9069ee45c", "order_id": "…", "amount_cents": 8900}
```

| Campo | Significado |
|---|---|
| `ts` | Timestamp UTC |
| `level` | `info`, `warning`, `error` |
| `service` | Servicio que escribió el log |
| `logger` | Módulo de origen (`http` = log de acceso) |
| `msg` | Evento. Texto fijo, buscable |
| `request_id` | Identificador de la petición; se propaga entre servicios en la cabecera `x-request-id` |
| `exc` | Traceback, solo en errores no controlados |
| resto | Campos propios del evento (`order_id`, `reason`, `target`…) |

**Log de acceso**: cada request (salvo `/health` y `/metrics`) genera un log
`msg: "request"` con `method`, `path`, `status` y `duration_ms`. Su nivel depende
del status: `info` (< 400), `warning` (4xx), `error` (5xx).

**Etiquetas en Loki**: `service` y `level`. El resto se filtra con `| json`.

```logql
{service="shop", level="error"}                                  # errores de shop
{service=~".+"} |= "854e6e9cfe85405b9ceb7fb9069ee45c"            # una petición en todos los servicios
{service="shop"} | json | msg="order failed" | reason="out_of_stock"
sum by (service) (count_over_time({level="error"}[5m]))          # errores por servicio
```

Postgres y Redis también envían sus logs a Loki (`service="postgres"`,
`service="redis"`), en su formato de texto nativo.

## Métricas

Todas llevan la etiqueta `service`, que Prometheus pone al scrapear.

| Métrica | Tipo | Etiquetas | Qué mide |
|---|---|---|---|
| `http_requests_total` | counter | `method`, `route`, `status` | Requests atendidas |
| `http_request_duration_seconds` | histogram | `method`, `route` | Latencia de requests atendidas |
| `upstream_requests_total` | counter | `target`, `status` | Llamadas a otros servicios. `status` es el código HTTP, `timeout` o `error` (conexión fallida) |
| `upstream_request_duration_seconds` | histogram | `target` | Latencia de llamadas a otros servicios |
| `orders_total` | counter | `status`, `reason` | Pedidos por resultado (solo `shop`, ver [shop.md](services/shop.md)) |

`route` es la plantilla de la ruta (`/users/{user_id}`), no la URL concreta.

```promql
# Throughput por servicio
sum by (service) (rate(http_requests_total[1m]))

# Tasa de error 5xx por servicio
sum by (service) (rate(http_requests_total{status=~"5.."}[5m]))
  / sum by (service) (rate(http_requests_total[5m]))

# Latencia p95 por servicio y ruta
histogram_quantile(0.95, sum by (service, route, le) (rate(http_request_duration_seconds_bucket[5m])))

# Latencia p95 de shop hacia cada dependencia
histogram_quantile(0.95, sum by (target, le) (rate(upstream_request_duration_seconds_bucket[5m])))

# Pedidos por resultado
sum by (status, reason) (rate(orders_total[5m]))
```
