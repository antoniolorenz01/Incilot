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
        """Catálogo y reservas."""


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
    assert "Catálogo y reservas" in code.page_content  # contexto del módulo
    assert docs["config/inventory.env"].metadata["service"] == "inventory"


def test_docs_are_split_by_section(tmp_path):
    write(
        tmp_path / "services/shop.md",
        "# shop\n\nintro\n\n## Endpoints\n\nGET\n\n## Datos\n\norders\n",
    )
    sources = [d.metadata["source"] for d in corpus.docs(tmp_path)]
    assert sources == [
        "docs/services/shop.md#shop",
        "docs/services/shop.md#Endpoints",
        "docs/services/shop.md#Datos",
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
    write(tmp_path / "pool.md", "# Pool agotado\nRevisar DB_POOL_SIZE y conexiones idle.")
    write(tmp_path / "latencia.md", "# Latencia alta\nRevisar el p95.")
    docs = corpus.runbooks(tmp_path)
    retriever = index.build_retriever(docs, store_with(docs), top_n=1, rerank=False, mode="bm25")
    [best] = asyncio.run(retriever.ainvoke("DB_POOL_SIZE"))
    assert best.metadata["source"] == "runbooks/pool.md"


def test_sync_adds_new_fragments_and_deletes_stale_ones(tmp_path):
    write(tmp_path / "a.md", "uno")
    write(tmp_path / "b.md", "dos")
    old = corpus.runbooks(tmp_path)
    store = store_with(old)
    write(tmp_path / "b.md", "dos, editado")
    new = corpus.runbooks(tmp_path)
    added, deleted = asyncio.run(index.sync(store, new, {d.id for d in old}))
    assert (added, deleted) == (1, 1)


def test_fragment_ids_are_canonical_uuids(tmp_path):
    """pgvector guarda los ids como UUID: si no coinciden al leerlos, la sincronización
    cree que todo es viejo y borra el índice (pasó)."""
    import uuid

    write(tmp_path / "a.md", "uno")
    [doc] = corpus.runbooks(tmp_path)
    assert doc.id == str(uuid.UUID(doc.id))


def test_tokenize_ignores_case_accents_and_punctuation():
    assert index.tokenize("Latencia alta, reposición: DB_POOL_SIZE") == [
        "latencia",
        "alta",
        "reposicion",
        "db_pool_size",
    ]
