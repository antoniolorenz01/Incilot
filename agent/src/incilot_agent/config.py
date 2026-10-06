"""Dónde están las fuentes que investiga el agente. Todo por variables de entorno."""

import os
from pathlib import Path

PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://localhost:9090")
LOKI_URL = os.getenv("LOKI_URL", "http://localhost:3100")
# Repo Git de la empresa, montado en solo lectura.
COMPANY_REPO = Path(os.getenv("COMPANY_REPO", "build/company-repo"))
RUNBOOKS_DIR = Path(os.getenv("RUNBOOKS_DIR", "../incilot-data/runbooks"))
# Usuario `agent` de Postgres: solo lectura, sin acceso a groundtruth.
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "postgres")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
AGENT_DB_USER = os.getenv("AGENT_DB_USER", "agent")
AGENT_DB_PASSWORD = os.getenv("AGENT_DB_PASSWORD", "agent")
# Base propia del agente (dueño: `agent`): checkpoints de las investigaciones.
AGENT_STATE_URL = os.getenv(
    "AGENT_STATE_URL",
    f"postgresql://{AGENT_DB_USER}:{AGENT_DB_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/agent_state",
)
