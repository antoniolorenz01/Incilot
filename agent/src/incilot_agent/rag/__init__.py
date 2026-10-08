"""Hybrid search (RAG) over the company's runbooks, docs and code."""

import logging

# The SDKs' HTTP calls (embeddings) are logged at INFO: console noise.
for _name in ("httpx", "httpx2"):
    logging.getLogger(_name).setLevel(logging.WARNING)
