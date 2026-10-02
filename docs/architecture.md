# Arquitectura de la mini-empresa

Una tienda online pequeña: los clientes ven el catálogo y hacen pedidos. Cuatro
microservicios, cada uno con su propia base de datos, y un generador de tráfico
que simula clientes.

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

| Servicio | Responsabilidad | Doc |
|---|---|---|
| `shop` | Única entrada de clientes. Catálogo y pedidos; orquesta al resto | [shop.md](services/shop.md) |
| `users` | Perfiles de usuario | [users.md](services/users.md) |
| `inventory` | Catálogo, stock y reservas | [inventory.md](services/inventory.md) |
| `payments` | Cobros contra un proveedor externo simulado | [payments.md](services/payments.md) |
| `traffic` | Clientes virtuales que compran sin parar | [traffic.md](services/traffic.md) |

## Flujo de un pedido

`POST /orders` en `shop`:

1. `GET users/users/{id}`: el usuario existe. Si no → **404** `user_not_found`.
2. `GET inventory/products/{id}`: precio del producto. Si no existe → **404** `product_not_found`.
3. Inserta el pedido en estado `pending`.
4. `POST inventory/reservations`: reserva stock. Sin stock → pedido `failed`, **409** `out_of_stock`.
5. `POST payments/charges`: cobra. Rechazado → libera la reserva, pedido `failed`, **402** `payment_declined`.
6. Pedido `confirmed` → **201**.

Si un servicio no responde (timeout de 2 s) o devuelve 5xx, `shop` responde **502**.
Si eso pasa después de crear el pedido, el pedido queda `failed` y se libera la
reserva si la había (ver [shop.md](services/shop.md)).

## Infraestructura

- **Postgres 16**: una instancia, una base por servicio (`users`, `inventory`,
  `payments`, `shop`). Cada servicio crea sus tablas al arrancar.
- **Redis 7**: caché. `users` usa la db 0, `shop` la db 1.
- **Prometheus, Loki, Alloy y Grafana**: observabilidad, ver [observability.md](observability.md).

Todos los servicios corren con la misma imagen (`sim/Dockerfile`), escuchan en el
puerto 8000 dentro de la red de Docker y exponen `/health` y `/metrics`. Solo
`shop` se publica en el host (`localhost:8000`).
