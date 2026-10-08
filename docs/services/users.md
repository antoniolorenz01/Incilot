# users

User profiles. `shop` queries it to check that the customer exists.

Code: `sim/src/incilot_sim/services/users.py`

## Endpoints

| Method and path | Response |
|---|---|
| `GET /users/{user_id}` | `id`, `email`, `name`, `tier`. 404 `user_not_found` if it does not exist |

## Data

**Postgres**, database `users`, table `users`: `id`, `email` (unique), `name`, `tier`
(`standard` or `premium`), `created_at`.

On startup with an empty table, 500 users are loaded (IDs 1–500,
`user{i}@example.com`). One in ten is `premium`.

**Redis**, db 0: key `user:{id}` holding the profile, TTL 300 s. Only users that
exist are cached.

## Configuration

| Variable | Value in compose |
|---|---|
| `DATABASE_URL` | `postgresql://incilot:incilot@postgres:5432/users` |
| `REDIS_URL` | `redis://redis:6379/0` |
| `DB_POOL_SIZE` | 10 (default) |
| `LOG_LEVEL` | `INFO` (default) |

## Service-specific logs

| `msg` | Level | Fields |
|---|---|---|
| `seeded users` | info | `count` |

## Failure behaviour

- **Redis down**: every lookup returns 500; the cache is read before Postgres.
- **Postgres down**: users that are not cached return 500.
- In both cases `shop` sees it as `users_error` (502).
