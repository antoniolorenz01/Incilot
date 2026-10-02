# shop

Tienda online: única entrada de los clientes. Sirve el catálogo y procesa pedidos
orquestando a `users`, `inventory` y `payments`.

Código: `sim/src/incilot_sim/services/shop.py`

## Endpoints

| Método y ruta | Respuesta |
|---|---|
| `GET /products` | Catálogo (viene de `inventory`, cacheado en Redis 30 s) |
| `POST /orders` | Crea un pedido. Body: `user_id`, `product_id`, `quantity` (1–10, por defecto 1) |
| `GET /orders/{order_id}` | Un pedido. 404 `order_not_found` si no existe |

### Respuestas de `POST /orders`

| Status | `detail` | Cuándo |
|---|---|---|
| 201 | — | Pedido confirmado: `order_id`, `status`, `amount_cents` |
| 404 | `user_not_found` | `users` no conoce al usuario |
| 404 | `product_not_found` | `inventory` no conoce el producto |
| 409 | `out_of_stock` | No hay stock suficiente |
| 402 | `payment_declined` | `payments` rechazó el cobro |
| 502 | `{servicio}_unavailable` | Timeout o conexión fallida con `users`, `inventory` o `payments` |
| 502 | `{servicio}_error` | Ese servicio respondió 5xx |
| 502 | `inventory_unavailable` / `payments_unavailable` | Falló la reserva o el cobro de un pedido ya creado |

El flujo completo está en [architecture.md](../architecture.md#flujo-de-un-pedido).

## Datos

**Postgres**, base `shop`, tabla `orders`:

| Columna | Notas |
|---|---|
| `id` | UUID del pedido |
| `user_id`, `product_id`, `quantity`, `amount_cents` | `amount_cents` = precio × cantidad |
| `status` | `pending` → `confirmed` o `failed` |
| `failure_reason` | `out_of_stock`, `payment_declined`, `inventory_unavailable`, `payments_unavailable` |
| `created_at`, `updated_at` | |

Los pedidos rechazados antes de crearse (usuario o producto inexistente, o fallo
de `users` o del lookup a `inventory`) no dejan fila.

**Redis**, db 1: clave `catalog` con el catálogo, TTL 30 s.

## Dependencias

| Servicio | Llamada | Variable |
|---|---|---|
| `users` | `GET /users/{id}` | `USERS_URL` |
| `inventory` | `GET /products`, `GET /products/{id}`, `POST /reservations`, `POST /reservations/{id}/release` | `INVENTORY_URL` |
| `payments` | `POST /charges` | `PAYMENTS_URL` |

Timeout de 2 s por llamada, sin reintentos.

## Configuración

| Variable | Valor en compose |
|---|---|
| `DATABASE_URL` | `postgresql://incilot:incilot@postgres:5432/shop` |
| `REDIS_URL` | `redis://redis:6379/1` |
| `USERS_URL`, `INVENTORY_URL`, `PAYMENTS_URL` | `http://{servicio}:8000` |
| `DB_POOL_SIZE` | 10 (por defecto) |
| `LOG_LEVEL` | `INFO` (por defecto) |

## Métricas propias

`orders_total{status, reason}`:

| `status` | `reason` |
|---|---|
| `confirmed` | vacío |
| `rejected` | `user_not_found`, `product_not_found` |
| `failed` | `out_of_stock`, `payment_declined`, `inventory_unavailable`, `payments_unavailable` |

## Logs propios

| `msg` | Nivel | Campos |
|---|---|---|
| `order confirmed` | info | `order_id`, `amount_cents` |
| `order failed` | warning | `order_id`, `reason` |
| `upstream unavailable` | error | `target`, `error` |
| `upstream error` | error | `target`, `status` |
| `reservation release failed` | error | `order_id` |

## Comportamiento ante fallos

- **`users` o `inventory` caídos**: los pedidos fallan con 502 antes de crearse.
  `GET /products` sigue funcionando mientras el catálogo esté en caché.
- **`payments` caído o lento (> 2 s)**: el pedido queda `failed`
  (`payments_unavailable`) y se libera la reserva de stock.
- **Falla la liberación de una reserva**: se loguea `reservation release failed`;
  ese stock queda reservado hasta la próxima reposición de `inventory`.
- **Redis caído**: `GET /products` responde 500 (la caché no es opcional). Los
  pedidos fallan con 502 `users_error`, porque `users` también depende de Redis.
- **Postgres caído**: es una instancia compartida, así que los pedidos fallan con
  502 en la primera dependencia que lo necesite (`users_error` si el usuario no
  está en caché, si no `inventory_error`). `GET /orders/{id}` responde 500.
