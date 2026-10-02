# Incilot

IncidentPilot: un agente que investiga y resuelve incidentes en una mini-empresa simulada.

## Estructura

```
sim/        Mini-empresa simulada (microservicios, tráfico, logs, métricas)
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
```
