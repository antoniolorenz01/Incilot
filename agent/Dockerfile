# Imagen del agente: solo el paquete agent (sin el código de la simulación ni el
# injector). Corre como usuario sin privilegios. Se construye desde la raíz del repo.
FROM python:3.12-slim
# git: las herramientas leen el historial del repo de la empresa.
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

USER nobody
