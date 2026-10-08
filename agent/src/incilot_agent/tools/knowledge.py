"""Knowledge base search: runbooks, docs, and the company's code and config.

Before searching it checks whether the corpus has changed (the company repo changes with
every deploy) and, if so, syncs the index: embeddings are computed only for what is new.
"""

import os

import asyncpg

from incilot_agent import config
from incilot_agent.rag import corpus, index
from incilot_agent.tools._guard import ToolError, guarded

MAX_FRAGMENT = 1500
SEARCH_MODE = os.getenv("KNOWLEDGE_SEARCH_MODE", "vector")  # vector, hybrid or bm25
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


@guarded(timeout=90)  # the first time it embeds the whole corpus
async def search_knowledge(query: str, limit: int = 3) -> str:
    """Search runbooks, service docs, and the company's code and config by meaning.
    Returns the most relevant fragments with their source: e.g. a runbook, a doc
    section or a function such as services/inventory/handlers.py::list_products."""
    if not 1 <= limit <= 8:
        raise ToolError("limit must be between 1 and 8")
    state = await _ready_index()
    # Configuration chosen with `make rag-eval` (TONI-100): vectors alone gave the best
    # recall@3 (91%, what the agent sees) versus hybrid (77%) and BM25 (64%); the
    # reranker worsened recall and MRR and was ~10x slower.
    retriever = index.build_retriever(
        state["docs"], state["store"], top_n=limit, rerank=False, mode=SEARCH_MODE
    )
    results = await retriever.ainvoke(query)
    if not results:
        return f"nothing relevant for {query!r}"
    return "\n\n---\n\n".join(
        f"[{d.metadata['source']}] ({d.metadata['kind']})\n{d.page_content[:MAX_FRAGMENT]}"
        for d in results
    )
