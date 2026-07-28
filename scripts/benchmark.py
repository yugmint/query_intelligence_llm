#!/usr/bin/env python
"""
Automated retrieval + generation benchmark, against real indexes with
real questions -- replaces the ad-hoc manual spot-checking this project
relied on all session (grep the git history for "PRIOR:"/"NOW:" diffs
printed by one-off scripts). Ground truth below reuses question/answer/
source/page triples already hand-verified against real document text
earlier this session, not invented.

Two kinds of thing measured per question:

  Retrieval quality (from the raw ranked candidate list, before
  reranking trims it) -- Hit@1, Hit@3, Recall@5, MRR, Precision@5.
  Binary relevance only (a chunk counts as relevant iff it's on
  `expected_page` of `expected_source`) -- real nDCG needs graded
  relevance judgments this project doesn't have, and would collapse to
  the same signal Hit@K/MRR already give under binary relevance, so
  it's deliberately not implemented here.

  End-to-end answer quality (real RAGService.ask() call) --
  answer_correct (any of expected_answer_substring's keywords found,
  case-insensitive -- OR, for expect_refusal=True cases, whether the
  answer actually hedged), citation_correct (expected_page appears in
  the returned citations, or must_cite=True is satisfied by any
  citation at all), potential_hallucination (a confident, non-hedged
  answer that doesn't match -- a heuristic proxy via a phrase list,
  not an LLM-judged hallucination detector), and latency.

Also includes a graded subset of "Benchmark document for the history
book.docx" (an external benchmark spec, ~115 questions across 7
difficulty levels, received 2026-07-28): Level 5 "Synonyms" (5
questions) and Level 6 "Failure Tests" (10 questions) are the only
levels that state expected answers/behavior in that document, so
they're the only ones graded here. Levels 1-4 and the rest of Level 5
give question text only -- grading those needs the same real
hand-verification-against-the-source-PDF already done for every other
case in this file, not invented from the question alone.

Usage:
    python scripts/benchmark.py
"""

import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

CASES = [
    # Factor Analysis -- local/test_reports/factor_analysis_index
    dict(
        dataset="Factor Analysis",
        level="Manual Spot-Check",
        index_path="local/test_reports/factor_analysis_index",
        question="Who documented the scree graph?",
        expected_answer_substring="cattell",
        expected_source="Factor_Analysis.pdf",
        expected_page=3,
    ),
    dict(
        dataset="Factor Analysis",
        level="Manual Spot-Check",
        index_path="local/test_reports/factor_analysis_index",
        question="In Example 1, how many factors were retained, and what rotation was used?",
        expected_answer_substring="varimax",
        expected_source="Factor_Analysis.pdf",
        expected_page=None,  # not pinned down by hand this session -- answer-substring check only
    ),
    # EfficientNet -- local/test_reports/efficientnet_index
    dict(
        dataset="EfficientNet",
        level="Manual Spot-Check",
        index_path="local/test_reports/efficientnet_index",
        question="Where is the EfficientNet source code available?",
        expected_answer_substring="github.com/tensorflow/tpu",
        expected_source="EfficientNet.pdf",
        expected_page=None,
    ),
    dict(
        dataset="EfficientNet",
        level="Manual Spot-Check",
        index_path="local/test_reports/efficientnet_index",
        question="What accuracy does EfficientNet achieve on CIFAR-100 and Flowers in transfer learning?",
        expected_answer_substring="91.7",
        expected_source="EfficientNet.pdf",
        expected_page=None,
    ),
    # Airlock (COVID-19 severity study) -- local/test_reports/airlock_index
    dict(
        dataset="Airlock",
        level="Manual Spot-Check",
        index_path="local/test_reports/airlock_index",
        question="What was the sample size in this study?",
        expected_answer_substring="40 patients",
        expected_source=None,
        expected_page=None,
    ),
    # History book -- F:/.../ingestion_fixed/local/test_reports/history_book_index_v2
    dict(
        dataset="History Book",
        level="Manual Spot-Check",
        index_path=r"F:\Programming\RAG Projects\ingestion_fixed\local\test_reports\history_book_index_v2",
        question="Which schools of art were connected with Mahayana Buddhism?",
        expected_answer_substring="gandhara",
        expected_source="ede93-history.pdf",
        expected_page=41,
    ),
    dict(
        dataset="History Book",
        level="Manual Spot-Check",
        index_path=r"F:\Programming\RAG Projects\ingestion_fixed\local\test_reports\history_book_index_v2",
        question="What was the outcome of the 1971 Indo-Pak War?",
        expected_answer_substring="victory",
        expected_source="ede93-history.pdf",
        expected_page=101,
    ),
]

# ---------------------------------------------------------------------
# "Benchmark document for history book.docx" -- an external benchmark
# spec (~115 questions across 7 difficulty levels) received 2026-07-28.
# Only the two levels that actually carry stated expected answers/
# behavior in that document are included here as graded cases; Levels
# 1-4 (75 questions) and most of Level 5 give only the question text,
# no expected answer -- grading those needs the same real hand-
# verification-against-the-source-PDF this session already did for the
# CASES above, not invented from the question alone. Not done here;
# a separate task if wanted.
# ---------------------------------------------------------------------

_HISTORY_INDEX = r"F:\Programming\RAG Projects\ingestion_fixed\local\test_reports\history_book_index_v2"

CASES += [
    # Level 5 -- Retrieval Robustness / Synonyms subsection. The
    # benchmark doc states these five expected answers explicitly.
    dict(dataset="History Book", level="L5-Synonyms", index_path=_HISTORY_INDEX,
         question="Which civilization built excellent sewer systems?",
         expected_answer_substring=["harappan", "indus valley"], expected_source=None, expected_page=None),
    dict(dataset="History Book", level="L5-Synonyms", index_path=_HISTORY_INDEX,
         question="Who promoted moral governance?",
         expected_answer_substring="ashoka", expected_source=None, expected_page=None),
    dict(dataset="History Book", level="L5-Synonyms", index_path=_HISTORY_INDEX,
         question="Which empire first unified much of India?",
         expected_answer_substring="mauryan", expected_source=None, expected_page=None),
    dict(dataset="History Book", level="L5-Synonyms", index_path=_HISTORY_INDEX,
         question="Which civilization used bronze extensively?",
         # "harappan" alone false-negatived a real run: the model
         # correctly answered "Indus Valley Civilization" -- the same
         # entity, just the source's other name for it. Same fix would
         # apply to any other Harappan/Indus-Valley question here.
         expected_answer_substring=["harappan", "indus valley"],
         expected_source=None, expected_page=None),
    dict(dataset="History Book", level="L5-Synonyms", index_path=_HISTORY_INDEX,
         question="Which culture worshipped Proto-Shiva?",
         expected_answer_substring=["harappan", "indus valley"], expected_source=None, expected_page=None),

    # Level 6 -- Failure Tests. The benchmark doc states these should
    # NOT be answered confidently -- success here means a refusal/hedge,
    # the opposite polarity from every other case (expect_refusal=True).
    dict(dataset="History Book", level="L6-Failure Tests", index_path=_HISTORY_INDEX,
         question="Who was the last Harappan king?",
         expect_refusal=True, expected_source=None, expected_page=None),
    dict(dataset="History Book", level="L6-Failure Tests", index_path=_HISTORY_INDEX,
         question="Which language did Harappans speak?",
         expect_refusal=True, expected_source=None, expected_page=None),
    dict(dataset="History Book", level="L6-Failure Tests", index_path=_HISTORY_INDEX,
         question="What was Ashoka's favorite animal?",
         expect_refusal=True, expected_source=None, expected_page=None),
    dict(dataset="History Book", level="L6-Failure Tests", index_path=_HISTORY_INDEX,
         question="Give Harappan population figures.",
         expect_refusal=True, expected_source=None, expected_page=None),
    dict(dataset="History Book", level="L6-Failure Tests", index_path=_HISTORY_INDEX,
         question="What currency did Harappans use?",
         expect_refusal=True, expected_source=None, expected_page=None),
    dict(dataset="History Book", level="L6-Failure Tests", index_path=_HISTORY_INDEX,
         question="Who wrote the Harappan script?",
         expect_refusal=True, expected_source=None, expected_page=None),
    dict(dataset="History Book", level="L6-Failure Tests", index_path=_HISTORY_INDEX,
         question="What color were Harappan houses?",
         expect_refusal=True, expected_source=None, expected_page=None),
    dict(dataset="History Book", level="L6-Failure Tests", index_path=_HISTORY_INDEX,
         question="Which Mahajanapada had the largest army?",
         expect_refusal=True, expected_source=None, expected_page=None),
    dict(dataset="History Book", level="L6-Failure Tests", index_path=_HISTORY_INDEX,
         question="How many Harappan kings existed?",
         expect_refusal=True, expected_source=None, expected_page=None),
    dict(dataset="History Book", level="L6-Failure Tests", index_path=_HISTORY_INDEX,
         question="What was the exact cause of Harappan decline?",
         expect_refusal=True, expected_source=None, expected_page=None),
]

for _case in CASES:
    _case.setdefault("level", "Manual Spot-Check")
    _case.setdefault("must_cite", False)
    _case.setdefault("expect_refusal", False)


def _is_relevant(document, expected_source, expected_page) -> bool:
    if expected_page is None:
        return False  # can't judge retrieval-rank relevance without a page to match
    meta = document.metadata
    if expected_source and meta.get("source") != expected_source:
        return False
    return meta.get("page_number") == expected_page


def retrieval_metrics(vectorstore, query, expected_source, expected_page, k=15):
    if expected_page is None:
        return None

    ranked = vectorstore.similarity_search(query, k=k)
    relevant_ranks = [
        i + 1 for i, d in enumerate(ranked) if _is_relevant(d, expected_source, expected_page)
    ]

    return {
        "hit@1": len(relevant_ranks) > 0 and relevant_ranks[0] == 1,
        "hit@3": any(r <= 3 for r in relevant_ranks),
        "recall@5": any(r <= 5 for r in relevant_ranks),
        "mrr": (1.0 / relevant_ranks[0]) if relevant_ranks else 0.0,
        "precision@5": sum(1 for r in relevant_ranks if r <= 5) / 5,
    }


# Broader than a literal "i don't know" -- Level 6 "Failure Tests" cases
# (scripts/benchmark.py CASES, is_refusal=True) expect a hedge/refusal
# phrased any number of ways ("not mentioned", "the document does not
# specify", "no information about", etc.), not that one exact sentence.
_REFUSAL_PHRASES = [
    "i don't know",
    "not mentioned",
    "not specified",
    "not available",
    "not stated",
    "not provided",
    "no information",
    "does not mention",
    "does not specify",
    "does not provide",
    "does not state",
    "unclear from",
    "cannot determine",
    "unable to determine",
    "insufficient information",
    "no mention of",
    "the document does not",
    "not indicate",
]


def _is_refusal(answer_lower: str) -> bool:
    return any(phrase in answer_lower for phrase in _REFUSAL_PHRASES)


def generation_metrics(rag_service, case):
    start = time.perf_counter()
    state = rag_service.ask(case["question"], session_id=f"bench-{hash(case['question'])}", return_state=True)
    latency = time.perf_counter() - start

    answer = state["answer"]
    answer_lower = answer.lower()
    is_refusal = _is_refusal(answer_lower)

    if case.get("expect_refusal"):
        # Level 6 "Failure Tests": success means the system correctly
        # declined rather than confidently answering with something
        # unsupported -- the opposite polarity from every other case.
        answer_correct = is_refusal
        potential_hallucination = not is_refusal
    else:
        keywords = case["expected_answer_substring"]
        if isinstance(keywords, str):
            keywords = [keywords]
        answer_correct = any(kw.lower() in answer_lower for kw in keywords)
        potential_hallucination = (not answer_correct) and (not is_refusal)

    citation_correct = None
    if case.get("expected_page") is not None:
        citation_correct = any(
            c.get("page") == case["expected_page"]
            and (case["expected_source"] is None or c.get("source") == case["expected_source"])
            for c in state["citations"]
        )
    elif case.get("must_cite"):
        citation_correct = len(state["citations"]) > 0

    return {
        "answer_correct": answer_correct,
        "potential_hallucination": potential_hallucination,
        "citation_correct": citation_correct,
        "latency": latency,
    }


def _pct(values):
    values = [v for v in values if v is not None]
    return 100 * sum(1 for v in values if v) / len(values) if values else float("nan")


def _mean(values):
    values = [v for v in values if v is not None]
    return statistics.mean(values) if values else float("nan")


def _build_rag_service(index_path, embeddings, reranker, llm):
    """
    RAGService normally builds its own resources via build_resources(),
    which reads FAISS_INDEX_PATH once at *import* time (a `from ... import
    FAISS_PATH` binding in vectorstore.py) -- setting the env var again
    mid-process, to switch between this script's several datasets, would
    silently do nothing (a real bug hit and root-caused earlier this
    session running ad-hoc multi-dataset comparison scripts the same way).
    Sidesteps it entirely: build RAGResources directly from an explicitly
    loaded vectorstore, and monkeypatch build_resources for just this one
    RAGService() construction -- the same technique tests/test_rag_service_*
    already use to inject fake resources.
    """
    import src.services.rag_service as rag_service_module
    from src.retrieval.bm25 import BM25Factory
    from src.retrieval.retriever import RetrieverFactory
    from src.workflow.resources import RAGResources
    from langchain_community.vectorstores import FAISS

    vectorstore = FAISS.load_local(index_path, embeddings, allow_dangerous_deserialization=True)
    resources = RAGResources(
        llm=llm,
        embeddings=embeddings,
        vectorstore=vectorstore,
        retriever=RetrieverFactory.build(vectorstore),
        reranker=reranker,
        bm25_retriever=BM25Factory.build(vectorstore),
    )

    original_build_resources = rag_service_module.build_resources
    rag_service_module.build_resources = lambda: resources
    try:
        service = rag_service_module.RAGService()
    finally:
        rag_service_module.build_resources = original_build_resources

    return service, vectorstore


def main():
    from src.retrieval.embeddings import EmbeddingFactory
    from src.retrieval.llm import LLMFactory
    from src.retrieval.reranker import RerankerFactory

    embeddings = EmbeddingFactory.get()
    reranker = RerankerFactory.get()
    llm = LLMFactory.get()

    results = []
    for case in CASES:
        index_path = case["index_path"]
        if not Path(index_path).exists():
            print(f"SKIP  {case['dataset']!r} / {case['question']!r} -- index not found at {index_path}")
            continue

        rag_service, vectorstore = _build_rag_service(index_path, embeddings, reranker, llm)

        r = retrieval_metrics(vectorstore, case["question"], case["expected_source"], case["expected_page"])
        g = generation_metrics(rag_service, case)

        results.append({**case, "retrieval": r, "generation": g})

        label = "refusal_correct" if case["expect_refusal"] else "answer_correct"
        print(f"[{case['level']:<16}] {case['question'][:55]:<55} "
              f"{label}={g['answer_correct']!s:<5} "
              f"latency={g['latency']:.2f}s")

    def _report(label, rows):
        gen = [r["generation"] for r in rows]
        ret = [r["retrieval"] for r in rows if r["retrieval"] is not None]

        print()
        print("=" * 78)
        print(label)
        print("=" * 78)
        print(f"Questions run:            {len(rows)}")
        print(f"Answer correctness:       {_pct([g['answer_correct'] for g in gen]):.0f}%")
        print(f"Potential hallucination:  {_pct([g['potential_hallucination'] for g in gen]):.0f}%  (heuristic proxy, see module docstring)")
        judgeable = sum(1 for g in gen if g['citation_correct'] is not None)
        print(f"Citation accuracy:        {_pct([g['citation_correct'] for g in gen]):.0f}%  (of {judgeable} judgeable)")
        print(f"Mean latency:             {_mean([g['latency'] for g in gen]):.2f}s  (target from the benchmark doc: <2s)")
        if ret:
            print(f"Retrieval Hit@1:          {_pct([r['hit@1'] for r in ret]):.0f}%  (of {len(ret)} judgeable)")
            print(f"Retrieval Hit@3:          {_pct([r['hit@3'] for r in ret]):.0f}%")
            print(f"Retrieval Recall@5:       {_pct([r['recall@5'] for r in ret]):.0f}%")
            print(f"Retrieval MRR:            {_mean([r['mrr'] for r in ret]):.2f}")
            print(f"Retrieval Precision@5:    {_mean([r['precision@5'] for r in ret]):.2f}")

    levels = sorted({r["level"] for r in results})
    for level in levels:
        _report(f"LEVEL: {level}", [r for r in results if r["level"] == level])

    _report("OVERALL", results)

    print()
    print("Note: 'Confidence Score' (a target metric in the benchmark doc's")
    print("Production Benchmark table) is not implemented -- deliberately")
    print("skipped, see docs/05-roadmap.md v0.5.0 'confidence calibration'.")


if __name__ == "__main__":
    main()
