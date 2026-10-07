install:
	uv sync

lint:
	uv run ruff check .
	uv run ruff format --check .

fmt:
	uv run ruff check --fix .
	uv run ruff format .

test:
	uv run pytest

check: lint test

up:
	docker compose up --build -d

down:
	docker compose down

# Como down, pero borra también los datos (Postgres, repo de la empresa).
clean:
	docker compose down -v --remove-orphans

logs:
	docker compose logs -f

# make injector ARGS="inject deploy-latency-regression"
injector:
	docker compose exec injector python -m incilot_sim.injector.cli $(ARGS)

# make smoke [ARGS="escenario ..."]: inyecta cada escenario, mide el síntoma y recupera.
smoke:
	uv run python scripts/smoke_scenarios.py $(ARGS)

# Verifica que el agente no llegue a la respuesta (groundtruth, faults:*).
agent-access:
	docker compose exec -T injector python -m incilot_sim.agent_access

# make investigate [ARGS="descripción de la alerta"]: el agente investiga lo que esté pasando.
investigate:
	docker compose build -q agent-api
	docker compose up -d --quiet-pull
	docker compose run --rm agent python -m incilot_agent.investigate $(ARGS)

# Corre cada herramienta del agente una vez desde su contenedor (incluida la base).
agent-tools:
	docker compose build -q agent-api
	docker compose up -d --quiet-pull
	docker compose run --rm agent python -m incilot_agent.investigate --check-tools

# Lanza una investigación dry_run por la API, la sigue por SSE y la aprueba (sin tokens).
agent-api-check:
	uv run python -m incilot_agent.apicheck

# Examen del RAG: recall@k y MRR por configuración (BM25, vectores, híbrido, + reranker).
rag-eval:
	docker compose build -q agent-api
	docker compose up -d --quiet-pull
	docker compose run --rm agent python -m incilot_agent.rag.evaluate

company-repo:
	uv run python -m incilot_sim.company_repo

.PHONY: install lint fmt test check up down clean logs injector smoke agent-access investigate agent-tools agent-api-check rag-eval company-repo
