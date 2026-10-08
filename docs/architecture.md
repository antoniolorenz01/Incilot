# Architecture of the simulated company

A small online shop: customers browse the catalogue and place orders. Four
microservices, each with its own database, plus a traffic generator that
simulates customers.

```
                 ┌──────────┐
  traffic ──────▶│   shop   │──── Postgres (shop) + Redis (db 1)
                 └────┬─────┘
          ┌───────────┼────────────┐
          ▼           ▼            ▼
     ┌───────┐  ┌───────────┐  ┌──────────┐
     │ users │  │ inventory │  │ payments │
     └───┬───┘  └─────┬─────┘  └────┬─────┘
   Postgres (users)  Postgres     Postgres
   + Redis (db 0)   (inventory)  (payments)
```

| Service | Responsibility | Doc |
|---|---|---|
| `shop` | Single entry point for customers. Catalogue and orders; orchestrates the rest | [shop.md](services/shop.md) |
| `users` | User profiles | [users.md](services/users.md) |
| `inventory` | Catalogue, stock and reservations | [inventory.md](services/inventory.md) |
| `payments` | Charges against a simulated external provider | [payments.md](services/payments.md) |
| `traffic` | Virtual shoppers that buy non-stop | [traffic.md](services/traffic.md) |

## Order flow

`POST /orders` on `shop`:

1. `GET users/users/{id}`: the user exists. If not → **404** `user_not_found`.
2. `GET inventory/products/{id}`: the product's price. If it does not exist → **404** `product_not_found`.
3. Inserts the order with status `pending`.
4. `POST inventory/reservations`: reserves stock. Out of stock → order `failed`, **409** `out_of_stock`.
5. `POST payments/charges`: charges. Declined → releases the reservation, order `failed`, **402** `payment_declined`.
6. Order `confirmed` → **201**.

If a service does not respond (2 s timeout) or returns a 5xx, `shop` returns **502**.
If that happens after the order has been created, the order is marked `failed` and
the reservation, if any, is released (see [shop.md](services/shop.md)).

## Infrastructure

- **Postgres 16**: one instance, one database per service (`users`, `inventory`,
  `payments`, `shop`). Each service creates its tables on startup.
- **Redis 7**: cache. `users` uses db 0, `shop` db 1.
- **Prometheus, Loki, Alloy and Grafana**: observability, see [observability.md](observability.md).

All services run from the same image (`sim/Dockerfile`), listen on port 8000
inside the Docker network and expose `/health` and `/metrics`. Only `shop` is
published on the host (`localhost:8000`).
