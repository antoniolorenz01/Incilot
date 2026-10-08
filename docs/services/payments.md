# payments

Charges for orders against an external payment provider, simulated inside the
service itself.

Code: `sim/src/incilot_sim/services/payments.py`

## Endpoints

| Method and path | Response |
|---|---|
| `POST /charges` | Charges an order. Body: `order_id`, `user_id`, `amount_cents` (> 0). 201 with `payment_id` and `status: captured`; 402 `card_declined`; 409 `duplicate_charge` |

## Simulated provider

- Each charge takes between 50 and 200 ms (provider latency).
- 3 % of charges are declined (`PAYMENTS_DECLINE_RATE`).

## Data

**Postgres**, database `payments`, table `payments`: `id` (UUID), `order_id` (unique),
`user_id`, `amount_cents`, `status` (`captured` or `declined`), `created_at`.

Declined charges are stored too. Because `order_id` is unique, an order is
charged only once: a second attempt returns 409.

## Configuration

| Variable | Value in compose |
|---|---|
| `DATABASE_URL` | `postgresql://incilot:incilot@postgres:5432/payments` |
| `PAYMENTS_DECLINE_RATE` | 0.03 (default) |
| `DB_POOL_SIZE` | 10 (default) |
| `LOG_LEVEL` | `INFO` (default) |

Does not use Redis.

## Service-specific logs

| `msg` | Level | Fields |
|---|---|---|
| `payment declined` | warning | `order_id`, `reason` |

## Failure behaviour

- **Postgres down**: charges return 500; `shop` marks the order `failed`
  (`payments_unavailable`) and releases the reservation.
- **Latency > 2 s**: `shop` times out even if the charge completes later.
  This can leave a `captured` charge for a `failed` order.
