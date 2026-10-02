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

logs:
	docker compose logs -f

company-repo:
	uv run python -m incilot_sim.company_repo

.PHONY: install lint fmt test check up down logs company-repo
