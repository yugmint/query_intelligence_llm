#!/usr/bin/env python
"""
Measure the latency reranking adds to retrieval, on real indexes with real
questions.

Follow-up flagged (not measured) in
docs/reports/2026-07-24-reranking-validation.md §5: reranking added a
cross-encoder forward pass over RERANK_CANDIDATES query/chunk pairs to
every knowledge query, but the report shipped without quantifying the
added cost. This script closes that gap.

Compares two retrieval paths against the same real FAISS indexes used in
that report:

  BEFORE  -- FAISS search alone, k=TOP_K (3)      (pre-reranking behavior)
  AFTER   -- FAISS search, k=RERANK_CANDIDATES (15), then cross-encoder
             rerank down to TOP_K                  (current behavior)

Usage:
    python scripts/measure_reranking_latency.py
"""

import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from langchain_community.vectorstores import FAISS

from src.retrieval.config import RERANK_CANDIDATES, TOP_K
from src.retrieval.embeddings import EmbeddingFactory
from src.retrieval.reranker import RerankerFactory

DATASETS = [
    (
        "Factor Analysis",
        "local/test_reports/factor_analysis_index",
        "local/test_reports/qa_results.json",
    ),
    (
        "EfficientNet",
        "local/test_reports/efficientnet_index",
        "local/test_reports/qa_results_efficientnet.json",
    ),
]


def load_questions(path: str) -> list[str]:
    import json

    with open(path, encoding="utf-8") as f:
        return [row["question"] for row in json.load(f)]


def time_before(vectorstore, query: str) -> float:
    """FAISS search alone at k=TOP_K -- the pre-reranking retrieval path."""
    start = time.perf_counter()
    vectorstore.similarity_search(query, k=TOP_K)
    return time.perf_counter() - start


def time_after(vectorstore, reranker, query: str) -> tuple[float, float, float]:
    """FAISS search at k=RERANK_CANDIDATES, then cross-encoder rerank to TOP_K.

    Returns (retrieval_seconds, rerank_seconds, total_seconds).
    """
    start = time.perf_counter()
    candidates = vectorstore.similarity_search(query, k=RERANK_CANDIDATES)
    retrieval_time = time.perf_counter() - start

    pairs = [(query, doc.page_content) for doc in candidates]
    rerank_start = time.perf_counter()
    reranker.predict(pairs)
    rerank_time = time.perf_counter() - rerank_start

    return retrieval_time, rerank_time, retrieval_time + rerank_time


def summarize(label: str, values: list[float]) -> None:
    print(
        f"{label:<28} min={min(values)*1000:7.1f}ms  "
        f"median={statistics.median(values)*1000:7.1f}ms  "
        f"mean={statistics.mean(values)*1000:7.1f}ms  "
        f"max={max(values)*1000:7.1f}ms"
    )


def main():
    embeddings = EmbeddingFactory.get()

    print("Loading reranker (cross-encoder) -- one-time cost, excluded from")
    print("per-query timings below.")
    reranker = RerankerFactory.get()
    print()

    for label, index_path, qa_path in DATASETS:
        if not Path(index_path).exists() or not Path(qa_path).exists():
            print(f"Skipping {label}: {index_path} or {qa_path} not found.\n")
            continue

        print("=" * 78)
        print(f"{label}  ({index_path})")
        print("=" * 78)

        vectorstore = FAISS.load_local(
            index_path, embeddings, allow_dangerous_deserialization=True
        )
        questions = load_questions(qa_path)

        # Warm-up query -- first FAISS/cross-encoder call on a freshly
        # loaded index pays a one-time init cost that would otherwise
        # skew the first measured sample.
        time_before(vectorstore, questions[0])
        time_after(vectorstore, reranker, questions[0])

        before_times = [time_before(vectorstore, q) for q in questions]
        retrieval_times, rerank_times, after_times = [], [], []
        for q in questions:
            r, rr, total = time_after(vectorstore, reranker, q)
            retrieval_times.append(r)
            rerank_times.append(rr)
            after_times.append(total)

        summarize("BEFORE (k=3, no rerank)", before_times)
        summarize("AFTER retrieval (k=15)", retrieval_times)
        summarize("AFTER rerank only", rerank_times)
        summarize("AFTER total (k=15+rerank)", after_times)

        added_ms = (statistics.mean(after_times) - statistics.mean(before_times)) * 1000
        print(f"\nAdded latency vs pre-reranking (mean): {added_ms:.1f}ms per query")
        print(
            f"Rerank pass alone (mean): "
            f"{statistics.mean(rerank_times)*1000:.1f}ms "
            f"over {RERANK_CANDIDATES} candidates, {len(questions)} queries\n"
        )


if __name__ == "__main__":
    main()
