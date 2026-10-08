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

# Like down, but also deletes the data (Postgres, company repo).
clean:
	docker compose down -v --remove-orphans

logs:
	docker compose logs -f

# make injector ARGS="inject deploy-latency-regression"
injector:
	docker compose exec injector python -m incilot_sim.injector.cli $(ARGS)

# make smoke [ARGS="scenario ..."]: injects each scenario, measures the symptom and recovers.
smoke:
	uv run python scripts/smoke_scenarios.py $(ARGS)

# Checks that the agent cannot reach the answer (groundtruth, faults:*).
agent-access:
	docker compose exec -T injector python -m incilot_sim.agent_access

# make investigate [ARGS="alert description"]: the agent investigates whatever is going on.
investigate:
	docker compose build -q agent-api
	docker compose up -d --quiet-pull
	docker compose run --rm agent python -m incilot_agent.investigate $(ARGS)

# Runs each agent tool once from its container (including the database).
agent-tools:
	docker compose build -q agent-api
	docker compose up -d --quiet-pull
	docker compose run --rm agent python -m incilot_agent.investigate --check-tools

# Starts a dry_run investigation through the API, follows it over SSE and approves it (no tokens).
agent-api-check:
	uv run python -m incilot_agent.apicheck

# RAG exam: recall@k and MRR per configuration (BM25, vectors, hybrid, + reranker).
rag-eval:
	docker compose build -q agent-api
	docker compose up -d --quiet-pull
	docker compose run --rm agent python -m incilot_agent.rag.evaluate

# Evals: runs the catalogue and grades the agent against the ground truth (spends tokens).
# make eval ARGS="--split dev --limit 5"
eval:
	docker compose build -q agent-api
	docker compose up -d --quiet-pull
	uv run python -m incilot_evals.run $(ARGS)

# Replays for the public demo: full investigations (approved, verified) saved to
# web/public/replays. Spends one real investigation each.
record:
	docker compose up -d --quiet-pull
	uv run python -m incilot_evals.record $(ARGS)

# Claude Code as the agent's model (local only, on your subscription): leave this running
# and set LLM_PROVIDER=claude-code in .env, then `make up`. Needs `claude` logged in.
claude-bridge:
	uv run python -m incilot_agent.claude_code

# Web UI (Next.js) at http://localhost:3001, against the `make up` environment.
web:
	cd web && npm run dev

# Public demo (on the server; see infra/deploy.md).
PROD = docker compose -f compose.yaml -f compose.prod.yaml

prod-up:
	$(PROD) up -d --build

prod-logs:
	$(PROD) logs -f --tail 100 web agent-worker caddy

backup:
	scripts/backup.sh

company-repo:
	uv run python -m incilot_sim.company_repo

.PHONY: install lint fmt test check up down clean logs injector smoke agent-access investigate agent-tools agent-api-check rag-eval eval record claude-bridge web prod-up prod-logs backup company-repo
