# The agent image: only the agent package (without the simulation code or the
# injector). Runs as an unprivileged user. Built from the repo root.
FROM python:3.12-slim
# git: the tools read the company repo's history.
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /bin/uv

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PATH="/app/.venv/bin:$PATH"

COPY pyproject.toml uv.lock ./
COPY sim/pyproject.toml sim/
COPY agent/pyproject.toml agent/
RUN uv sync --frozen --no-dev --package incilot-agent --no-install-workspace

COPY agent/src agent/src
RUN uv sync --frozen --no-dev --package incilot-agent

# Reranker model (FlashRank, multilingual), downloaded when building the image.
ENV RERANK_CACHE_DIR=/opt/flashrank
RUN python -c "from flashrank import Ranker; Ranker(model_name='ms-marco-MultiBERT-L-12', cache_dir='/opt/flashrank')"

USER nobody
