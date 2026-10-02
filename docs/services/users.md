# users

Perfiles de usuario. Lo consulta `shop` para validar que el cliente existe.

Código: `sim/src/incilot_sim/services/users.py`

## Endpoints

| Método y ruta | Respuesta |
|---|---|
| `GET /users/{user_id}` | `id`, `email`, `name`, `tier`. 404 `user_not_found` si no existe |

## Datos

**Postgres**, base `users`, tabla `users`: `id`, `email` (único), `name`, `tier`
(`standard` o `premium`), `created_at`.

Al arrancar con la tabla vacía se cargan 500 usuarios (IDs 1–500,
`user{i}@example.com`). Uno de cada diez es `premium`.

**Redis**, db 0: clave `user:{id}` con el perfil, TTL 300 s. Solo se cachean
usuarios que existen.

## Configuración

| Variable | Valor en compose |
|---|---|
| `DATABASE_URL` | `postgresql://incilot:incilot@postgres:5432/users` |
| `REDIS_URL` | `redis://redis:6379/0` |
| `DB_POOL_SIZE` | 10 (por defecto) |
| `LOG_LEVEL` | `INFO` (por defecto) |

## Logs propios

| `msg` | Nivel | Campos |
|---|---|---|
| `seeded users` | info | `count` |

## Comportamiento ante fallos

- **Redis caído**: todas las consultas responden 500; la caché se lee antes que Postgres.
- **Postgres caído**: responden 500 los usuarios que no están en caché.
- En ambos casos `shop` lo ve como `users_error` (502).
