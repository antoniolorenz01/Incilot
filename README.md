# Incilot

IncidentPilot: un agente que investiga y resuelve incidentes en una mini-empresa simulada.

## Estructura

```
sim/        Mini-empresa simulada (microservicios, tráfico, logs, métricas)
docs/       Arquitectura, observabilidad y doc de cada servicio
infra/      Configuración de Postgres, Prometheus, Loki/Alloy y Grafana
compose.yaml  Levanta la mini-empresa y la observabilidad
.github/    CI (lint + tests)
```

Los datos sintéticos (repo de la empresa, incidentes con ground truth) viven
en un repo aparte para poder ampliarlos sin tocar este.

## Desarrollo

Requisitos: [uv](https://docs.astral.sh/uv/), Docker con el plugin compose, `make`.

```bash
make install   # uv sync
make check     # lint + tests
make fmt       # autoformato
make up        # levanta todo (docker compose)
make logs      # sigue los logs
make down      # apaga todo
make company-repo  # genera el repo Git de la empresa desde ../incilot-data
```

## La mini-empresa

| Servicio    | Qué hace                                             | Datos            |
|-------------|------------------------------------------------------|------------------|
| `shop`      | Entrada de clientes: catálogo y pedidos; orquesta al resto | Postgres + Redis |
| `users`     | Perfiles de usuario                                  | Postgres + Redis |
| `inventory` | Catálogo, stock y reservas (repone stock cada 30 s)  | Postgres         |
| `payments`  | Cobros contra un proveedor simulado (~3 % rechazos)  | Postgres         |
| `traffic`   | Usuarios virtuales que compran sin parar             | —                |

Un pedido: `shop` valida el usuario → consulta el producto → reserva stock →
cobra → confirma. Si el cobro falla, libera la reserva.

Todos los servicios loguean JSON con un `request_id` que viaja entre servicios y
exponen métricas en `/metrics`.

| Herramienta | URL                        | Para qué                     |
|-------------|----------------------------|------------------------------|
| Tienda      | http://localhost:8000/docs | API de la tienda             |
| Prometheus  | http://localhost:9090      | Métricas (latencia, errores) |
| Loki        | http://localhost:3100      | Logs (`{service="shop"}`)    |
| Grafana     | http://localhost:3000      | Explorar métricas y logs     |
