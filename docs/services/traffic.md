# traffic

Generador de tráfico: clientes virtuales que navegan y compran en `shop` sin parar.
No es parte de la empresa; simula a sus clientes.

Código: `sim/src/incilot_sim/traffic.py`

## Qué hace cada cliente virtual

1. `GET /products`.
2. Con probabilidad 60 %, `POST /orders` con un producto al azar, cantidad 1–3 y
   un `user_id` entre 1 y 520. Los IDs 501–520 no existen, así que ~4 % de los
   pedidos dan 404 `user_not_found` (ruido realista).
3. Espera entre 0,2 y 1,5 s y repite.

Con 5 clientes son unas 8 requests/s a `shop` (~5 de catálogo y ~3 pedidos).

## Configuración

| Variable | Valor en compose |
|---|---|
| `SHOP_URL` | `http://shop:8000` |
| `TRAFFIC_SHOPPERS` | 5 |
| `LOG_LEVEL` | `INFO` (por defecto) |

## Logs

| `msg` | Nivel | Campos |
|---|---|---|
| `traffic started` | info | `shop_url`, `shoppers` |
| `traffic summary` | info | `window_seconds`, `counts` |

`traffic summary` se escribe cada 30 s con el recuento de respuestas, visto desde
el cliente:

```json
{"msg": "traffic summary", "window_seconds": 30,
 "counts": {"GET /products 200": 120, "POST /orders 201": 65, "POST /orders 402": 2, "POST /orders 404": 3}}
```

Los errores de red aparecen como `error {Excepción}` (por ejemplo `error ReadTimeout`).
No expone métricas.
