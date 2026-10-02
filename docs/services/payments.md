# payments

Cobros de pedidos contra un proveedor de pagos externo, simulado dentro del propio
servicio.

Código: `sim/src/incilot_sim/services/payments.py`

## Endpoints

| Método y ruta | Respuesta |
|---|---|
| `POST /charges` | Cobra un pedido. Body: `order_id`, `user_id`, `amount_cents` (> 0). 201 con `payment_id` y `status: captured`; 402 `card_declined`; 409 `duplicate_charge` |

## Proveedor simulado

- Cada cobro tarda entre 50 y 200 ms (latencia del proveedor).
- Un 3 % de los cobros se rechaza (`PAYMENTS_DECLINE_RATE`).

## Datos

**Postgres**, base `payments`, tabla `payments`: `id` (UUID), `order_id` (único),
`user_id`, `amount_cents`, `status` (`captured` o `declined`), `created_at`.

Se guardan también los cobros rechazados. Como `order_id` es único, un pedido se
cobra una sola vez: un segundo intento responde 409.

## Configuración

| Variable | Valor en compose |
|---|---|
| `DATABASE_URL` | `postgresql://incilot:incilot@postgres:5432/payments` |
| `PAYMENTS_DECLINE_RATE` | 0.03 (por defecto) |
| `DB_POOL_SIZE` | 10 (por defecto) |
| `LOG_LEVEL` | `INFO` (por defecto) |

No usa Redis.

## Logs propios

| `msg` | Nivel | Campos |
|---|---|---|
| `payment declined` | warning | `order_id`, `reason` |

## Comportamiento ante fallos

- **Postgres caído**: los cobros responden 500; `shop` marca el pedido `failed`
  (`payments_unavailable`) y libera la reserva.
- **Latencia > 2 s**: `shop` corta por timeout aunque el cobro termine después.
  Puede quedar un cobro `captured` de un pedido `failed`.
