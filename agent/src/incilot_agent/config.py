"""Where the sources the agent investigates live. All set via environment variables."""

import os
from pathlib import Path

PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://localhost:9090")
LOKI_URL = os.getenv("LOKI_URL", "http://localhost:3100")
# The company's Git repo, mounted read-only.
COMPANY_REPO = Path(os.getenv("COMPANY_REPO", "build/company-repo"))
RUNBOOKS_DIR = Path(os.getenv("RUNBOOKS_DIR", "../incilot-data/runbooks"))
DOCS_DIR = Path(os.getenv("DOCS_DIR", "docs"))
# Postgres user `agent`: read-only, no access to groundtruth.
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "postgres")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
AGENT_DB_USER = os.getenv("AGENT_DB_USER", "agent")
AGENT_DB_PASSWORD = os.getenv("AGENT_DB_PASSWORD", "agent")
# The agent's own database (owner: `agent`): investigation checkpoints.
AGENT_STATE_URL = os.getenv(
    "AGENT_STATE_URL",
    f"postgresql://{AGENT_DB_USER}:{AGENT_DB_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/agent_state",
)
# The agent's own Redis (not the shop's): job queue and per-investigation events.
AGENT_REDIS_URL = os.getenv("AGENT_REDIS_URL", "redis://default:agent@agent-redis:6379/0")
# Executor of approved actions (simulation connector): the operations service.
OPS_URL = os.getenv("OPS_URL")
OPS_TOKEN = os.getenv("OPS_TOKEN")
# RAG: embedding model (OpenAI) and its vector dimension.
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
EMBEDDING_DIMENSIONS = int(os.getenv("EMBEDDING_DIMENSIONS", "1536"))
# Local reranker (FlashRank, multilingual; kept from when the corpus was in Spanish).
RERANK_MODEL = os.getenv("RERANK_MODEL", "ms-marco-MultiBERT-L-12")
RERANK_CACHE_DIR = os.getenv("RERANK_CACHE_DIR", "/opt/flashrank")
