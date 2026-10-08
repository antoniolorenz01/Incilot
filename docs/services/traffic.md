# traffic

Traffic generator: virtual shoppers that browse and buy from `shop` non-stop.
It is not part of the company; it simulates the company's customers.

Code: `sim/src/incilot_sim/traffic.py`

## What each virtual shopper does

1. `GET /products`.
2. With 60 % probability, `POST /orders` with a random product, quantity 1–3 and
   a `user_id` between 1 and 520. IDs 501–520 do not exist, so ~4 % of orders
   get a 404 `user_not_found` (realistic noise).
3. Waits between 0.2 and 1.5 s and repeats.

With 5 shoppers that is about 8 requests/s to `shop` (~5 catalogue and ~3 orders).

## Configuration

| Variable | Value in compose |
|---|---|
| `SHOP_URL` | `http://shop:8000` |
| `TRAFFIC_SHOPPERS` | 5 |
| `LOG_LEVEL` | `INFO` (default) |

## Logs

| `msg` | Level | Fields |
|---|---|---|
| `traffic started` | info | `shop_url`, `shoppers` |
| `traffic summary` | info | `window_seconds`, `counts` |

`traffic summary` is written every 30 s with a count of responses, as seen from
the client side:

```json
{"msg": "traffic summary", "window_seconds": 30,
 "counts": {"GET /products 200": 120, "POST /orders 201": 65, "POST /orders 402": 2, "POST /orders 404": 3}}
```

Network errors appear as `error {Exception}` (for example `error ReadTimeout`).
It exposes no metrics.
