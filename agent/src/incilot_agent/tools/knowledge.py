"""Búsqueda en la base de conocimiento: runbooks, docs y el código y la config de la empresa.

Antes de buscar comprueba si el corpus cambió (el repo de la empresa cambia con cada
deploy) y, si cambió, sincroniza el índice: solo se calculan embeddings de lo nuevo.
"""

import os

import asyncpg

from incilot_agent import config
from incilot_agent.rag import corpus, index
from incilot_agent.tools._guard import ToolError, guarded

MAX_FRAGMENT = 1500
SEARCH_MODE = os.getenv("KNOWLEDGE_SEARCH_MODE", "vector")  # vector, hybrid o bm25
_state: dict = {"signature": None, "docs": [], "store": None}


async def _indexed_ids() -> set[str]:
    conn = await asyncpg.connect(config.AGENT_STATE_URL)
    try:
        rows = await conn.fetch(f"SELECT langchain_id::text AS id FROM {index.TABLE}")
    finally:
        await conn.close()
    return {r["id"] for r in rows}


async def _ready_index() -> dict:
    docs = corpus.load()
    signature = frozenset(d.id for d in docs)
    if signature != _state["signature"]:
        store = _state["store"] or await index.pg_vector_store()
        await index.sync(store, docs, await _indexed_ids())
        _state.update(signature=signature, docs=docs, store=store)
    return _state


@guarded(timeout=90)  # la primera vez calcula los embeddings de todo el corpus
async def search_knowledge(query: str, limit: int = 3) -> str:
    """Busca en runbooks, docs de los servicios y el código y la config de la empresa
    por significado. Devuelve los fragmentos más relevantes con su origen:
    p. ej. un runbook, una sección de doc o una función como
    services/inventory/handlers.py::list_products."""
    if not 1 <= limit <= 5:
        raise ToolError("limit tiene que estar entre 1 y 5")
    state = await _ready_index()
    # Configuración elegida con `make rag-eval` (TONI-100): vectores solos daban el mejor
    # recall@3 (91 %, lo que ve el agente) frente a híbrido (77 %) y BM25 (64 %); el
    # reranker empeoraba recall y MRR y era ~10x más lento.
    retriever = index.build_retriever(
        state["docs"], state["store"], top_n=limit, rerank=False, mode=SEARCH_MODE
    )
    results = await retriever.ainvoke(query)
    if not results:
        return f"nada relevante para {query!r}"
    return "\n\n---\n\n".join(
        f"[{d.metadata['source']}] ({d.metadata['kind']})\n{d.page_content[:MAX_FRAGMENT]}"
        for d in results
    )
