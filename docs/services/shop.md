# shop

Online shop: the single entry point for customers. Serves the catalogue and
processes orders by orchestrating `users`, `inventory` and `payments`.

Code: `sim/src/incilot_sim/services/shop.py`

## Endpoints

| Method and path | Response |
|---|---|
| `GET /products` | Catalogue (from `inventory`, cached in Redis for 30 s) |
| `POST /orders` | Creates an order. Body: `user_id`, `product_id`, `quantity` (1–10, default 1) |
| `GET /orders/{order_id}` | One order. 404 `order_not_found` if it does not exist |

### `POST /orders` responses

| Status | `detail` | When |
|---|---|---|
| 201 | — | Order confirmed: `order_id`, `status`, `amount_cents` |
| 404 | `user_not_found` | `users` does not know the user |
| 404 | `product_not_found` | `inventory` does not know the product |
| 409 | `out_of_stock` | Not enough stock |
| 402 | `payment_declined` | `payments` declined the charge |
| 502 | `{service}_unavailable` | Timeout or failed connection to `users`, `inventory` or `payments` |
| 502 | `{service}_error` | That service returned a 5xx |
| 502 | `inventory_unavailable` / `payments_unavailable` | The reservation or charge failed for an order that had already been created |

The full flow is in [architecture.md](../architecture.md#order-flow).

## Data

**Postgres**, database `shop`, table `orders`:

| Column | Notes |
|---|---|
| `id` | Order UUID |
| `user_id`, `product_id`, `quantity`, `amount_cents` | `amount_cents` = price × quantity |
| `status` | `pending` → `confirmed` or `failed` |
| `failure_reason` | `out_of_stock`, `payment_declined`, `inventory_unavailable`, `payments_unavailable` |
| `created_at`, `updated_at` | |

Orders rejected before they are created (unknown user or product, or a failure
in `users` or in the `inventory` lookup) leave no row.

**Redis**, db 1: key `catalog` holding the catalogue, TTL 30 s.

## Dependencies

| Service | Call | Variable |
|---|---|---|
| `users` | `GET /users/{id}` | `USERS_URL` |
| `inventory` | `GET /products`, `GET /products/{id}`, `POST /reservations`, `POST /reservations/{id}/release` | `INVENTORY_URL` |
| `payments` | `POST /charges` | `PAYMENTS_URL` |

2 s timeout per call, no retries.

## Configuration

| Variable | Value in compose |
|---|---|
| `DATABASE_URL` | `postgresql://incilot:incilot@postgres:5432/shop` |
| `REDIS_URL` | `redis://redis:6379/1` |
| `USERS_URL`, `INVENTORY_URL`, `PAYMENTS_URL` | `http://{service}:8000` |
| `DB_POOL_SIZE` | 10 (default) |
| `LOG_LEVEL` | `INFO` (default) |

## Service-specific metrics

`orders_total{status, reason}`:

| `status` | `reason` |
|---|---|
| `confirmed` | empty |
| `rejected` | `user_not_found`, `product_not_found` |
| `failed` | `out_of_stock`, `payment_declined`, `inventory_unavailable`, `payments_unavailable` |

## Service-specific logs

| `msg` | Level | Fields |
|---|---|---|
| `order confirmed` | info | `order_id`, `amount_cents` |
| `order failed` | warning | `order_id`, `reason` |
| `upstream unavailable` | error | `target`, `error` |
| `upstream error` | error | `target`, `status` |
| `reservation release failed` | error | `order_id` |

## Failure behaviour

- **`users` or `inventory` down**: orders fail with 502 before they are created.
  `GET /products` keeps working while the catalogue is cached.
- **`payments` down or slow (> 2 s)**: the order ends up `failed`
  (`payments_unavailable`) and the stock reservation is released.
- **Releasing a reservation fails**: `reservation release failed` is logged;
  that stock stays reserved until the next `inventory` restock.
- **Redis down**: `GET /products` returns 500 (the cache is not optional).
  Orders fail with 502 `users_error`, because `users` also depends on Redis.
- **Postgres down**: it is a shared instance, so orders fail with 502 at the
  first dependency that needs it (`users_error` if the user is not cached,
  otherwise `inventory_error`). `GET /orders/{id}` returns 500.
