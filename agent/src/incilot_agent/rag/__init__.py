"""Búsqueda híbrida (RAG) sobre runbooks, docs y el código de la empresa."""

import logging

# Las llamadas HTTP de los SDK (embeddings) se loguean en INFO: ruido en consola.
for _name in ("httpx", "httpx2"):
    logging.getLogger(_name).setLevel(logging.WARNING)
