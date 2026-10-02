# Una sola imagen para todos los servicios de la mini-empresa; compose elige el comando.
# Se construye desde la raíz del repo porque el lockfile es del workspace.
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /bin/uv

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PATH="/app/.venv/bin:$PATH"

COPY pyproject.toml uv.lock ./
COPY sim/pyproject.toml sim/
RUN uv sync --frozen --no-dev --package incilot-sim --no-install-workspace

COPY sim/src sim/src
RUN uv sync --frozen --no-dev --package incilot-sim
