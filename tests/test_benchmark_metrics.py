"""
Tests for the pure metric-computation functions in scripts/benchmark.py.
Not testing main()/_build_rag_service -- those need a real index/LLM,
matching scripts/measure_reranking_latency.py's existing precedent of
being a manual dev-run script, not a CI-suite target.
"""

import math

import pytest
from langchain_core.documents import Document

from scripts.benchmark import _is_refusal, _is_relevant, _mean, _pct, retrieval_metrics


def _doc(source, page):
    return Document(page_content="x", metadata={"source": source, "page_number": page})


def test_is_relevant_matches_source_and_page():
    doc = _doc("a.pdf", 5)
    assert _is_relevant(doc, "a.pdf", 5) is True
    assert _is_relevant(doc, "a.pdf", 6) is False
    assert _is_relevant(doc, "b.pdf", 5) is False


def test_is_relevant_none_expected_page_always_false():
    doc = _doc("a.pdf", 5)
    assert _is_relevant(doc, "a.pdf", None) is False


def test_is_relevant_no_expected_source_matches_any_source():
    doc = _doc("whatever.pdf", 5)
    assert _is_relevant(doc, None, 5) is True


def test_is_relevant_list_of_pages_is_any_match():
    # A question can legitimately draw from more than one source page
    # (comparisons spanning two concepts) -- same any-match convention
    # as expected_answer_substring accepting a list.
    doc = _doc("a.pdf", 7)
    assert _is_relevant(doc, "a.pdf", [7, 12]) is True
    assert _is_relevant(doc, "a.pdf", [12, 19]) is False


class _FakeVectorStore:
    def __init__(self, documents):
        self._documents = documents

    def similarity_search(self, query, k):
        return self._documents[:k]


def test_retrieval_metrics_none_when_no_expected_page():
    vs = _FakeVectorStore([_doc("a.pdf", 1)])
    assert retrieval_metrics(vs, "q", "a.pdf", None) is None


def test_retrieval_metrics_hit_at_1():
    vs = _FakeVectorStore([_doc("a.pdf", 5), _doc("a.pdf", 1), _doc("a.pdf", 2)])
    m = retrieval_metrics(vs, "q", "a.pdf", 5)
    assert m["hit@1"] is True
    assert m["hit@3"] is True
    assert m["recall@5"] is True
    assert m["mrr"] == 1.0


def test_retrieval_metrics_hit_at_3_not_1():
    vs = _FakeVectorStore([_doc("a.pdf", 1), _doc("a.pdf", 2), _doc("a.pdf", 5)])
    m = retrieval_metrics(vs, "q", "a.pdf", 5)
    assert m["hit@1"] is False
    assert m["hit@3"] is True
    assert m["mrr"] == 1 / 3


def test_retrieval_metrics_not_found_at_all():
    vs = _FakeVectorStore([_doc("a.pdf", 1), _doc("a.pdf", 2)])
    m = retrieval_metrics(vs, "q", "a.pdf", 99)
    assert m["hit@1"] is False
    assert m["hit@3"] is False
    assert m["recall@5"] is False
    assert m["mrr"] == 0.0
    assert m["precision@5"] == 0.0


def test_pct_and_mean_ignore_none_and_handle_empty():
    assert _pct([True, True, False, None]) == pytest.approx(66.67, abs=0.1)
    assert _mean([1.0, 2.0, None]) == 1.5
    assert math.isnan(_pct([]))
    assert math.isnan(_mean([]))


@pytest.mark.parametrize(
    "answer",
    [
        "i don't know.",
        "this is not mentioned in the document.",
        "the document does not specify a value here.",
        "there is no information about this in the text.",
        "i am unable to determine the exact figure.",
    ],
)
def test_is_refusal_detects_hedge_phrases(answer):
    assert _is_refusal(answer) is True


@pytest.mark.parametrize(
    "answer",
    [
        "the sample size was 40 patients.",
        "cattell documented the scree graph in 1966.",
        "the mauryan empire first unified much of india.",
    ],
)
def test_is_refusal_false_for_confident_answers(answer):
    assert _is_refusal(answer) is False
