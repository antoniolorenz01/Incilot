# A single image for every service of the mini-company; compose picks the command.
# Built from the repo root because the lockfile belongs to the workspace.
FROM python:3.12-slim
# git: the injector commits and reverts in the company repo.
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /bin/uv

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PATH="/app/.venv/bin:$PATH"

COPY pyproject.toml uv.lock ./
COPY sim/pyproject.toml sim/
RUN uv sync --frozen --no-dev --package incilot-sim --no-install-workspace

COPY sim/src sim/src
RUN uv sync --frozen --no-dev --package incilot-sim
