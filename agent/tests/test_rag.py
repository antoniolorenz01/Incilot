import asyncio
import textwrap

from langchain_core.embeddings import DeterministicFakeEmbedding
from langchain_core.vectorstores import InMemoryVectorStore

from incilot_agent.rag import corpus, index


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text).lstrip())


def test_code_is_split_by_function_with_metadata(tmp_path):
    write(
        tmp_path / "services/inventory/handlers.py",
        '''
        """Catalogue and reservations."""


        async def list_products():
            return await db.fetch("SELECT * FROM products")


        async def reserve(order_id):
            pass
        ''',
    )
    write(tmp_path / "config/inventory.env", "DB_POOL_SIZE=10\n")
    docs = {d.metadata["source"]: d for d in corpus.company_repo(tmp_path)}

    code = docs["services/inventory/handlers.py::list_products"]
    assert code.metadata == {
        "source": "services/inventory/handlers.py::list_products",
        "kind": "code",
        "service": "inventory",
        "function": "list_products",
    }
    assert "SELECT * FROM products" in code.page_content
    assert "Catalogue and reservations" in code.page_content  # module context
    assert docs["config/inventory.env"].metadata["service"] == "inventory"


def test_docs_are_split_by_section(tmp_path):
    write(
        tmp_path / "services/shop.md",
        "# shop\n\nintro\n\n## Endpoints\n\nGET\n\n## Data\n\norders\n",
    )
    sources = [d.metadata["source"] for d in corpus.docs(tmp_path)]
    assert sources == [
        "docs/services/shop.md#shop",
        "docs/services/shop.md#Endpoints",
        "docs/services/shop.md#Data",
    ]


def test_fragment_id_changes_only_with_content(tmp_path):
    path = tmp_path / "config/shop.env"
    write(path, "TIMEOUT=2\n")
    first = corpus.company_repo(tmp_path)[0].id
    assert corpus.company_repo(tmp_path)[0].id == first
    write(path, "TIMEOUT=5\n")
    assert corpus.company_repo(tmp_path)[0].id != first


def store_with(docs):
    store = InMemoryVectorStore(DeterministicFakeEmbedding(size=32))
    asyncio.run(index.sync(store, docs, set()))
    return store


def test_bm25_side_of_hybrid_search_finds_exact_terms(tmp_path):
    write(tmp_path / "pool.md", "# Pool exhausted\nCheck DB_POOL_SIZE and idle connections.")
    write(tmp_path / "latency.md", "# High latency\nCheck the p95.")
    docs = corpus.runbooks(tmp_path)
    retriever = index.build_retriever(docs, store_with(docs), top_n=1, rerank=False, mode="bm25")
    [best] = asyncio.run(retriever.ainvoke("DB_POOL_SIZE"))
    assert best.metadata["source"] == "runbooks/pool.md"


def test_sync_adds_new_fragments_and_deletes_stale_ones(tmp_path):
    write(tmp_path / "a.md", "one")
    write(tmp_path / "b.md", "two")
    old = corpus.runbooks(tmp_path)
    store = store_with(old)
    write(tmp_path / "b.md", "two, edited")
    new = corpus.runbooks(tmp_path)
    added, deleted = asyncio.run(index.sync(store, new, {d.id for d in old}))
    assert (added, deleted) == (1, 1)


def test_fragment_ids_are_canonical_uuids(tmp_path):
    """pgvector stores ids as UUIDs: if they do not match when read back, syncing
    thinks everything is stale and deletes the index (it happened)."""
    import uuid

    write(tmp_path / "a.md", "one")
    [doc] = corpus.runbooks(tmp_path)
    assert doc.id == str(uuid.UUID(doc.id))


def test_tokenize_ignores_case_accents_and_punctuation():
    assert index.tokenize("High Latency, café: DB_POOL_SIZE") == [
        "high",
        "latency",
        "cafe",
        "db_pool_size",
    ]
