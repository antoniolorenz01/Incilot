# Incilot

IncidentPilot: an agent that investigates and resolves incidents in a simulated
small company.

## Layout

```
sim/        The simulated company (microservices, traffic, logs, metrics) and the fault injector
agent/      The investigating agent: tools, RAG, API and worker
evals/      Grades the agent's diagnoses against the ground truth
web/        Web UI (Next.js)
docs/       Architecture, observability and a doc per service
infra/      Postgres, Prometheus, Loki/Alloy and Grafana configuration
scripts/    Smoke test for the fault catalogue
compose.yaml  Brings up the company, the observability stack and the agent
.github/    CI (lint + tests)
```

The synthetic data (the company's Git repo and incidents with their ground truth)
lives in a separate repository, so it can grow without touching this one.

## Development

Requirements: [uv](https://docs.astral.sh/uv/), Docker with the compose plugin, `make`.

```bash
make install   # uv sync
make check     # lint + tests
make fmt       # auto-format
make up        # start everything (docker compose)
make logs      # follow the logs
make down      # stop everything (keeps the data)
make clean     # stop everything and delete the data
make company-repo  # build the company's Git repo from ../incilot-data
make smoke     # inject each fault, check its symptom shows up, recover
make investigate   # run the agent against whatever is happening right now
make eval      # run the fault catalogue and grade the agent (spends tokens)
make web       # web UI at http://localhost:3001
```

## The company

| Service     | What it does                                                 | Data             |
|-------------|--------------------------------------------------------------|------------------|
| `shop`      | Customer entry point: catalogue and orders; orchestrates the rest | Postgres + Redis |
| `users`     | User profiles                                                | Postgres + Redis |
| `inventory` | Catalogue, stock and reservations (restocks every 30 s)      | Postgres         |
| `payments`  | Charges against a simulated provider (~3 % declined)         | Postgres         |
| `traffic`   | Virtual shoppers that buy non-stop                           | —                |

An order: `shop` checks the user → looks up the product → reserves stock →
charges → confirms. If the charge fails, the reservation is released.

Every service logs JSON with a `request_id` that travels between services, and
exposes metrics on `/metrics`.

| Tool       | URL                        | What for                     |
|------------|----------------------------|------------------------------|
| Shop       | http://localhost:8000/docs | The shop's API               |
| Injector   | http://localhost:8100/docs | Inject and recover faults    |
| Agent      | http://localhost:8200/docs | Start, follow and approve investigations |
| Prometheus | http://localhost:9090      | Metrics (latency, errors)    |
| Loki       | http://localhost:3100      | Logs (`{service="shop"}`)    |
| Grafana    | http://localhost:3000      | Explore metrics and logs     |
