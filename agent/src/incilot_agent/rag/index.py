"""Index and hybrid search.

    index:   corpus ──► BM25 (in memory)
                    └──► embeddings (OpenAI) ──► pgvector (`knowledge` table in agent_state)
    search:  BM25 + vectors ──► EnsembleRetriever (Reciprocal Rank Fusion)
                            ──► FlashRank (reranker) ──► top N

Embeddings are cached by content: syncing only embeds new fragments (the company's code
changes with every injection) and deletes the ones that no longer exist.
"""

import functools
import re
import unicodedata

from langchain_classic.retrievers import ContextualCompressionRetriever, EnsembleRetriever
from langchain_community.document_compressors import FlashrankRerank
from langchain_community.retrievers import BM25Retriever
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from langchain_core.vectorstores import VectorStore

from incilot_agent import config

CANDIDATES = 10  # how many each method fetches before fusing and reranking
TABLE = "knowledge"
WORDS = re.compile(r"\w+")


def build_retriever(
    docs: list[Document],
    vector_store: VectorStore,
    *,
    top_n: int = 3,
    rerank: bool = True,
    mode: str = "hybrid",
) -> BaseRetriever:
    """mode: hybrid (BM25 + vectors), bm25 or vector. rerank: FlashRank over the result."""
    bm25 = BM25Retriever.from_documents(docs, k=CANDIDATES, preprocess_func=tokenize)
    vector = vector_store.as_retriever(search_kwargs={"k": CANDIDATES})
    base = {
        "bm25": bm25,
        "vector": vector,
        "hybrid": EnsembleRetriever(retrievers=[bm25, vector], weights=[0.5, 0.5]),
    }[mode]
    if not rerank:
        return _TopN(base=base, top_n=top_n)
    return ContextualCompressionRetriever(base_compressor=reranker(top_n), base_retriever=base)


def reranker(top_n: int) -> FlashrankRerank:
    return FlashrankRerank(client=_ranker(), top_n=top_n)


@functools.cache
def _ranker():
    import onnxruntime
    from flashrank import Ranker  # loads the model only once per process

    onnxruntime.set_default_logger_severity(3)  # errors only

    return Ranker(model_name=config.RERANK_MODEL, cache_dir=config.RERANK_CACHE_DIR)


def tokenize(text: str) -> list[str]:
    """For BM25: lowercase, accents stripped and split on words (not on spaces), so
    "Latency," and "latency" count as the same term."""
    plain = unicodedata.normalize("NFKD", text.lower()).encode("ascii", "ignore").decode()
    return WORDS.findall(plain)


class _TopN(BaseRetriever):
    """Truncates another retriever's result (to compare without a reranker)."""

    base: BaseRetriever
    top_n: int

    def _get_relevant_documents(self, query, *, run_manager):
        return self.base.invoke(query)[: self.top_n]

    async def _aget_relevant_documents(self, query, *, run_manager):
        return (await self.base.ainvoke(query))[: self.top_n]


async def pg_vector_store():
    """The `knowledge` table in agent_state (pgvector), created if needed."""
    from langchain_openai import OpenAIEmbeddings
    from langchain_postgres import PGEngine, PGVectorStore

    url = config.AGENT_STATE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)
    engine = PGEngine.from_connection_string(url=url)
    try:
        await engine.ainit_vectorstore_table(
            table_name=TABLE, vector_size=config.EMBEDDING_DIMENSIONS
        )
    except Exception as exc:  # already exists
        if "already exists" not in str(exc):
            raise
    embeddings = OpenAIEmbeddings(model=config.EMBEDDING_MODEL)
    return await PGVectorStore.create(engine=engine, embedding_service=embeddings, table_name=TABLE)


async def sync(store, docs: list[Document], indexed_ids: set[str]) -> tuple[int, int]:
    """Adds new fragments and deletes those that no longer exist. Returns (added, deleted)."""
    current = {d.id: d for d in docs}
    new = [d for doc_id, d in current.items() if doc_id not in indexed_ids]
    stale = list(indexed_ids - current.keys())
    if new:
        await store.aadd_documents(new, ids=[d.id for d in new])
    if stale:
        await store.adelete(ids=stale)
    return len(new), len(stale)
