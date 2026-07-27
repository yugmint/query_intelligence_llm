"""
Tests for nodes/rerank.py::rerank_documents.
"""

from langchain_core.documents import Document

from tests.conftest import FakeReranker, make_resources

from src.retrieval.config import TOP_K, TOP_K_NUMERIC
from src.workflow.nodes.rerank import rerank_documents


def _docs(*contents):
    return [Document(page_content=c) for c in contents]


def test_reorders_by_score_descending():
    candidates = _docs("low relevance", "high relevance", "medium relevance")
    # Scores line up 1:1 with candidates in the order given.
    reranker = FakeReranker([0.1, 0.9, 0.5])
    state = {"query": "q", "rewritten_query": "", "documents": candidates}

    result = rerank_documents(state, make_resources(reranker=reranker))

    assert [d.page_content for d in result["documents"]] == [
        "high relevance",
        "medium relevance",
        "low relevance",
    ]


def test_keeps_only_top_k():
    # More candidates than TOP_K -- confirms trimming actually happens.
    candidates = _docs(*[f"chunk {i}" for i in range(TOP_K + 5)])
    scores = list(reversed(range(len(candidates))))  # chunk 0 scores highest
    reranker = FakeReranker(scores)
    state = {"query": "q", "rewritten_query": "", "documents": candidates}

    result = rerank_documents(state, make_resources(reranker=reranker))

    assert len(result["documents"]) == TOP_K
    assert result["documents"][0].page_content == "chunk 0"


def test_context_rebuilt_from_reranked_top_k_only():
    candidates = _docs("keep me first", "keep me second", "drop me")
    reranker = FakeReranker([0.9, 0.5, 0.1])
    state = {"query": "q", "rewritten_query": "", "documents": candidates}

    result = rerank_documents(state, make_resources(reranker=reranker))

    assert result["context"] == "keep me first\n\nkeep me second\n\ndrop me"
    # (TOP_K=3 in current config, so all 3 survive here -- see the
    # test above for the actual trimming behavior with more candidates.)


def test_uses_rewritten_query_when_present():
    candidates = _docs("a", "b")
    reranker = FakeReranker([0.5, 0.5])
    state = {"query": "original", "rewritten_query": "resolved", "documents": candidates}

    rerank_documents(state, make_resources(reranker=reranker))

    queries_used = {pair[0] for call in reranker.calls for pair in call}
    assert queries_used == {"resolved"}


def test_falls_back_to_query_when_no_rewritten_query():
    candidates = _docs("a")
    reranker = FakeReranker([0.5])
    state = {"query": "original", "rewritten_query": "", "documents": candidates}

    rerank_documents(state, make_resources(reranker=reranker))

    queries_used = {pair[0] for call in reranker.calls for pair in call}
    assert queries_used == {"original"}


def test_empty_candidates_skips_reranker_entirely():
    reranker = FakeReranker([0.5])
    state = {"query": "q", "rewritten_query": "", "documents": []}

    result = rerank_documents(state, make_resources(reranker=reranker))

    assert result["documents"] == []
    assert result["context"] == ""
    assert reranker.call_count == 0


def test_fewer_candidates_than_top_k_keeps_all_of_them():
    candidates = _docs("only one")
    reranker = FakeReranker([0.9])
    state = {"query": "q", "rewritten_query": "", "documents": candidates}

    result = rerank_documents(state, make_resources(reranker=reranker))

    assert len(result["documents"]) == 1
    assert result["context"] == "only one"


def test_reference_section_candidates_are_dropped_before_reranking():
    body = Document(page_content="real body content", metadata={"is_reference_section": False})
    citation = Document(
        page_content="Someone. A Paper Title. Some Venue, 2020.",
        metadata={"is_reference_section": True},
    )
    # Even if the reranker would score the citation highest, it should
    # never reach it -- filtered out before scoring.
    reranker = FakeReranker([0.1, 0.99])
    state = {"query": "q", "rewritten_query": "", "documents": [body, citation]}

    result = rerank_documents(state, make_resources(reranker=reranker))

    assert result["documents"] == [body]
    assert reranker.call_count == 1
    assert len(reranker.calls[0]) == 1


def test_numeric_question_uses_wider_top_k():
    # More candidates than either TOP_K, fewer than TOP_K_NUMERIC --
    # confirms the numeric flag actually changes how many survive.
    n = TOP_K_NUMERIC - 1
    candidates = _docs(*[f"chunk {i}" for i in range(n)])
    scores = list(reversed(range(n)))
    reranker = FakeReranker(scores)
    state = {
        "query": "q",
        "rewritten_query": "",
        "documents": candidates,
        "is_numeric_question": True,
    }

    result = rerank_documents(state, make_resources(reranker=reranker))

    assert len(result["documents"]) == n  # all of them survive, more than TOP_K


def test_numeric_question_still_trims_beyond_top_k_numeric():
    candidates = _docs(*[f"chunk {i}" for i in range(TOP_K_NUMERIC + 5)])
    scores = list(reversed(range(len(candidates))))
    reranker = FakeReranker(scores)
    state = {
        "query": "q",
        "rewritten_query": "",
        "documents": candidates,
        "is_numeric_question": True,
    }

    result = rerank_documents(state, make_resources(reranker=reranker))

    assert len(result["documents"]) == TOP_K_NUMERIC


def test_non_numeric_question_keeps_default_top_k():
    candidates = _docs(*[f"chunk {i}" for i in range(TOP_K_NUMERIC)])
    scores = list(reversed(range(len(candidates))))
    reranker = FakeReranker(scores)
    state = {
        "query": "q",
        "rewritten_query": "",
        "documents": candidates,
        "is_numeric_question": False,
    }

    result = rerank_documents(state, make_resources(reranker=reranker))

    assert len(result["documents"]) == TOP_K


def test_missing_numeric_flag_defaults_to_default_top_k():
    # State built before this feature existed (or a node that never set
    # it) shouldn't accidentally widen -- absence must mean "no".
    candidates = _docs(*[f"chunk {i}" for i in range(TOP_K_NUMERIC)])
    scores = list(reversed(range(len(candidates))))
    reranker = FakeReranker(scores)
    state = {"query": "q", "rewritten_query": "", "documents": candidates}

    result = rerank_documents(state, make_resources(reranker=reranker))

    assert len(result["documents"]) == TOP_K


def test_falls_back_to_reference_candidates_if_nothing_else_available():
    # A query genuinely about citations -- don't filter down to zero
    # candidates just because everything retrieved is reference-section.
    citation = Document(
        page_content="Someone. A Paper Title. Some Venue, 2020.",
        metadata={"is_reference_section": True},
    )
    reranker = FakeReranker([0.9])
    state = {"query": "q", "rewritten_query": "", "documents": [citation]}

    result = rerank_documents(state, make_resources(reranker=reranker))

    assert result["documents"] == [citation]
