"""RAG exam: recall@1, recall@3 and MRR per configuration.

    python -m incilot_agent.rag.evaluate   # make rag-eval (in the agent container)

Compares BM25 alone, vectors alone, fusion (RRF) and fusion with a reranker on
questions.toml. It only costs the query embeddings (a few cents).
"""

import asyncio
import time
import tomllib
from pathlib import Path

from incilot_agent.rag import corpus, index
from incilot_agent.tools.knowledge import _ready_index

CONFIGS = {
    "bm25": {"mode": "bm25", "rerank": False},
    "vectors": {"mode": "vector", "rerank": False},
    "hybrid (RRF)": {"mode": "hybrid", "rerank": False},
    "hybrid + reranker": {"mode": "hybrid", "rerank": True},
}
DEPTH = 10  # for MRR: how far down the answer is searched for


def questions() -> list[dict]:
    return tomllib.loads((Path(__file__).parent / "questions.toml").read_text())["questions"]


def rank(results, expected: set[str]) -> int | None:
    """Position (1-based) of the first correct fragment, or None."""
    for position, doc in enumerate(results, start=1):
        if doc.metadata["source"] in expected:
            return position
    return None


async def evaluate() -> dict:
    state = await _ready_index()
    known = {d.metadata["source"] for d in state["docs"]}
    qs = questions()
    for q in qs:  # a question whose answer does not exist measures nothing
        missing = set(q["expected"]) - known
        assert not missing, f"expected fragments do not exist: {missing}"

    report = {}
    for name, options in CONFIGS.items():
        retriever = index.build_retriever(state["docs"], state["store"], top_n=DEPTH, **options)
        start = time.perf_counter()
        ranks = [rank(await retriever.ainvoke(q["query"]), set(q["expected"])) for q in qs]
        elapsed = (time.perf_counter() - start) / len(qs)
        report[name] = {
            "recall@1": sum(r == 1 for r in ranks) / len(qs),
            "recall@3": sum(r is not None and r <= 3 for r in ranks) / len(qs),
            "mrr": sum(1 / r for r in ranks if r) / len(qs),
            "ms": elapsed * 1000,
            "misses": [q["query"] for q, r in zip(qs, ranks, strict=True) if not r or r > 3],
        }
    return report


def main() -> None:
    report = asyncio.run(evaluate())
    print(f"{len(questions())} questions, {len(corpus.load())} fragments\n")
    print(f"{'configuration':22} {'recall@1':>9} {'recall@3':>9} {'MRR':>6} {'ms/query':>12}")
    for name, m in report.items():
        recall = f"{m['recall@1']:>9.0%} {m['recall@3']:>9.0%}"
        print(f"{name:22} {recall} {m['mrr']:>6.2f} {m['ms']:>12.0f}")
    best = max(report, key=lambda n: (report[n]["recall@3"], report[n]["mrr"]))
    print(f"\nbest: {best}")
    for miss in report[best]["misses"]:
        print(f"  not in the top 3: {miss}")


if __name__ == "__main__":
    main()
