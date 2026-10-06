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
	docker compose --profile agent build -q agent
	docker compose run --rm agent python -m incilot_agent.investigate $(ARGS)

# Corre cada herramienta del agente una vez desde su contenedor (incluida la base).
agent-tools:
	docker compose --profile agent build -q agent
	docker compose run --rm agent python -m incilot_agent.investigate --check-tools

company-repo:
	uv run python -m incilot_sim.company_repo

.PHONY: install lint fmt test check up down clean logs injector smoke agent-access investigate agent-tools company-repo
