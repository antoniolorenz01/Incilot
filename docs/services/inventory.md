# inventory

Catálogo de productos, stock y reservas de stock para pedidos.

Código: `sim/src/incilot_sim/services/inventory.py`

## Endpoints

| Método y ruta | Respuesta |
|---|---|
| `GET /products` | Todos los productos: `id`, `sku`, `name`, `price_cents`, `stock` |
| `GET /products/{product_id}` | Un producto. 404 `product_not_found` |
| `POST /reservations` | Reserva stock. Body: `order_id`, `product_id`, `quantity`. 201 con `remaining_stock`; 409 `out_of_stock`; 404 `product_not_found` |
| `POST /reservations/{order_id}/release` | Devuelve el stock de una reserva. 404 `reservation_not_found` si no existe o ya se liberó |

Reservar descuenta el stock y registra la reserva en una sola transacción: o pasan
las dos cosas o ninguna.

## Datos

**Postgres**, base `inventory`:

- `products`: `id`, `sku` (único), `name`, `price_cents`, `stock` (nunca negativo).
- `reservations`: `order_id` (clave primaria), `product_id`, `quantity`,
  `released`, `created_at`.

Al arrancar se cargan 10 productos (de `CB-001` a 9 € hasta `MN-001` a 249 €)
con 500 unidades cada uno. Si ya existen, no se tocan.

## Reposición de stock

Cada 30 s, los productos con menos de 100 unidades vuelven a 500. Se loguea
`restocked` con los SKUs repuestos.

## Configuración

| Variable | Valor en compose |
|---|---|
| `DATABASE_URL` | `postgresql://incilot:incilot@postgres:5432/inventory` |
| `DB_POOL_SIZE` | 10 (por defecto) |
| `LOG_LEVEL` | `INFO` (por defecto) |

No usa Redis.

## Logs propios

| `msg` | Nivel | Campos |
|---|---|---|
| `restocked` | info | `skus` |
| `restock failed` | error | `exc` |
| `reservation released` | info | `order_id` |

## Comportamiento ante fallos

- **Postgres caído**: todos los endpoints responden 500 y la reposición loguea
  `restock failed` cada 30 s. `shop` lo ve como `inventory_error` (502).
- **Reserva duplicada** (mismo `order_id`): responde 500. `shop` nunca reutiliza un `order_id`.
