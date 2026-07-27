"""
Tests for src/retrieval/hybrid.py::reciprocal_rank_fusion.
"""

from langchain_core.documents import Document

from src.retrieval.hybrid import reciprocal_rank_fusion


def _doc(content):
    return Document(page_content=content)


def test_empty_lists_returns_empty():
    assert reciprocal_rank_fusion([]) == []
    assert reciprocal_rank_fusion([[], []]) == []


def test_single_list_preserves_order():
    docs = [_doc("a"), _doc("b"), _doc("c")]

    assert reciprocal_rank_fusion([docs]) == docs


def test_document_in_both_lists_outranks_one_only_in_one():
    # "shared" appears at rank 1 in both lists -- should beat "only_a"
    # (rank 2 in one list only) and "only_b" (rank 2 in the other).
    shared = _doc("shared")
    only_a = _doc("only_a")
    only_b = _doc("only_b")
    list_a = [shared, only_a]
    list_b = [shared, only_b]

    result = reciprocal_rank_fusion([list_a, list_b])

    assert result[0] is shared
    assert {d.page_content for d in result[1:]} == {"only_a", "only_b"}


def test_appearing_in_both_lists_can_beat_top_rank_in_only_one():
    # shared_low: rank 5 in both lists -> score 2/(60+5) = 2/65 ≈ 0.0308.
    # first_in_a: rank 1 in one list, absent from the other -> 1/(60+1) = 1/61 ≈ 0.0164.
    # 2/65 > 1/61, so appearing in both lists (even at a lower rank) wins
    # over a rank-1-in-only-one-list document. Distinct padding per list
    # so nothing besides shared_low actually overlaps between them.
    first_in_a = _doc("first_in_a")
    shared_low = _doc("shared_low")
    padding_a = [_doc(f"pad_a_{i}") for i in range(3)]
    padding_b = [_doc(f"pad_b_{i}") for i in range(4)]

    list_a = [first_in_a] + padding_a + [shared_low]  # shared_low at rank 5
    list_b = padding_b + [shared_low]  # shared_low at rank 5

    result = reciprocal_rank_fusion([list_a, list_b])

    assert result[0] is shared_low


def test_documents_deduped_by_page_content_not_by_identity():
    # Two separate Document objects with identical page_content
    # represent the same underlying chunk and must be merged into one
    # fused entry, not counted twice.
    a1 = Document(page_content="same text")
    a2 = Document(page_content="same text")
    other = Document(page_content="different text")

    result = reciprocal_rank_fusion([[a1], [a2, other]])

    assert len(result) == 2
    assert {d.page_content for d in result} == {"same text", "different text"}
