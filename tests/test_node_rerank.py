"""
Tests for nodes/rerank.py::rerank_documents.
"""

from langchain_core.documents import Document

from tests.conftest import FakeReranker, make_resources

from src.retrieval.config import TOP_K, TOP_K_NUMERIC
from src.workflow.nodes.rerank import rerank_documents


def _docs(*contents):
    return [Document(page_content=c) for c in contents]


def _distinct_docs(n):
    # For tests that only care about top-k *count* mechanics, not
    # content. A simple "chunk {i}" template shares almost its entire
    # string across items (differing by one digit), which the dedup
    # logic added alongside this correctly flags as near-duplicate --
    # so these need content with essentially no character overlap
    # instead, to stay independent of that behavior.
    return _docs(*[chr(ord("a") + i) * 20 for i in range(n)])


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
    candidates = _distinct_docs(TOP_K + 5)
    scores = list(reversed(range(len(candidates))))  # first candidate scores highest
    reranker = FakeReranker(scores)
    state = {"query": "q", "rewritten_query": "", "documents": candidates}

    result = rerank_documents(state, make_resources(reranker=reranker))

    assert len(result["documents"]) == TOP_K
    assert result["documents"][0].page_content == candidates[0].page_content


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
    candidates = _distinct_docs(n)
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
    candidates = _distinct_docs(TOP_K_NUMERIC + 5)
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
    candidates = _distinct_docs(TOP_K_NUMERIC)
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
    candidates = _distinct_docs(TOP_K_NUMERIC)
    scores = list(reversed(range(len(candidates))))
    reranker = FakeReranker(scores)
    state = {"query": "q", "rewritten_query": "", "documents": candidates}

    result = rerank_documents(state, make_resources(reranker=reranker))

    assert len(result["documents"]) == TOP_K


def test_near_duplicate_candidate_is_skipped_for_a_distinct_lower_scorer():
    # B and C are near-duplicates of each other (one word changed in a
    # long shared sentence); without dedup, both would take TOP_K slots
    # and D (genuinely distinct, but lowest-scoring) would be dropped.
    a = Document(page_content="Sensitivity and specificity were 90.5% and 84.2%.")
    b = Document(
        page_content=(
            "The sample size was 40 patients enrolled in this retrospective "
            "cohort study conducted in Xi'an city for COVID-19 severity analysis."
        )
    )
    c = Document(
        page_content=(
            "The sample size was 40 patients enrolled in this retrospective "
            "cohort study conducted in Xi'an city for COVID-19 risk analysis."
        )
    )
    d = Document(page_content="Independent risk factors included age, hypertension, and lymphopenia.")
    candidates = [a, b, c, d]
    reranker = FakeReranker([4, 3, 2, 1])  # scores line up 1:1 with candidates
    state = {"query": "q", "rewritten_query": "", "documents": candidates}

    result = rerank_documents(state, make_resources(reranker=reranker))

    assert result["documents"] == [a, b, d]
    assert "risk analysis" not in result["context"]  # c's distinguishing text never appears


def test_no_near_duplicates_behaves_like_plain_top_k():
    # All distinct -- dedup should be a complete no-op here.
    candidates = _docs("low relevance", "high relevance", "medium relevance")
    reranker = FakeReranker([0.1, 0.9, 0.5])
    state = {"query": "q", "rewritten_query": "", "documents": candidates}

    result = rerank_documents(state, make_resources(reranker=reranker))

    assert [d.page_content for d in result["documents"]] == [
        "high relevance",
        "medium relevance",
        "low relevance",
    ]


def test_only_one_distinct_candidate_returns_fewer_than_top_k():
    # Every candidate beyond the first is a near-duplicate of it -- no
    # genuinely distinct chunk exists to fill the remaining TOP_K slots,
    # so the result should come back short rather than padded with dupes.
    original = "The imaging modality used was chest x-ray or computed tomography scan."
    near_dupe_1 = "The imaging modality used was chest x-ray or computed tomography scans."
    near_dupe_2 = "The imaging modality used was a chest x-ray or computed tomography scan."
    candidates = _docs(original, near_dupe_1, near_dupe_2)
    reranker = FakeReranker([0.9, 0.8, 0.7])
    state = {"query": "q", "rewritten_query": "", "documents": candidates}

    result = rerank_documents(state, make_resources(reranker=reranker))

    assert len(result["documents"]) == 1
    assert result["documents"][0].page_content == original


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
