# inventory

Product catalogue, stock and stock reservations for orders.

Code: `sim/src/incilot_sim/services/inventory.py`

## Endpoints

| Method and path | Response |
|---|---|
| `GET /products` | All products: `id`, `sku`, `name`, `price_cents`, `stock` |
| `GET /products/{product_id}` | One product. 404 `product_not_found` |
| `POST /reservations` | Reserves stock. Body: `order_id`, `product_id`, `quantity`. 201 with `remaining_stock`; 409 `out_of_stock`; 404 `product_not_found` |
| `POST /reservations/{order_id}/release` | Returns a reservation's stock. 404 `reservation_not_found` if it does not exist or was already released |

Reserving decrements the stock and records the reservation in a single
transaction: either both happen or neither does.

## Data

**Postgres**, database `inventory`:

- `products`: `id`, `sku` (unique), `name`, `price_cents`, `stock` (never negative).
- `reservations`: `order_id` (primary key), `product_id`, `quantity`,
  `released`, `created_at`.

On startup 10 products are loaded (from `CB-001` at €9 to `MN-001` at €249)
with 500 units each. Existing products are left untouched.

## Restocking

Every 30 s, products with fewer than 100 units are topped back up to 500.
`restocked` is logged with the restocked SKUs.

## Configuration

| Variable | Value in compose |
|---|---|
| `DATABASE_URL` | `postgresql://incilot:incilot@postgres:5432/inventory` |
| `DB_POOL_SIZE` | 10 (default) |
| `LOG_LEVEL` | `INFO` (default) |

Does not use Redis.

## Service-specific logs

| `msg` | Level | Fields |
|---|---|---|
| `restocked` | info | `skus` |
| `restock failed` | error | `exc` |
| `reservation released` | info | `order_id` |

## Failure behaviour

- **Postgres down**: every endpoint returns 500 and restocking logs
  `restock failed` every 30 s. `shop` sees it as `inventory_error` (502).
- **Duplicate reservation** (same `order_id`): returns 500. `shop` never reuses an `order_id`.
