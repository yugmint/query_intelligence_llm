"""
Tests for src/services/citations.py::build_citations.
"""

from langchain_core.documents import Document

from src.services.citations import build_citations


def test_empty_documents_returns_empty_list():
    assert build_citations([]) == []


def test_one_entry_per_document():
    docs = [
        Document(page_content="a", metadata={"source": "paper.pdf", "page_number": 3}),
        Document(page_content="b", metadata={"source": "paper.pdf", "page_number": 7}),
    ]

    assert build_citations(docs) == [
        {"source": "paper.pdf", "page": 3},
        {"source": "paper.pdf", "page": 7},
    ]


def test_dedupes_same_source_and_page():
    # Two chunks landing on the same page shouldn't produce two citations.
    docs = [
        Document(page_content="a", metadata={"source": "paper.pdf", "page_number": 5}),
        Document(page_content="b", metadata={"source": "paper.pdf", "page_number": 5}),
    ]

    assert build_citations(docs) == [{"source": "paper.pdf", "page": 5}]


def test_preserves_first_appearance_order():
    # documents is already relevance-ordered by the time this runs --
    # the most relevant citation should come first, not get resorted.
    docs = [
        Document(page_content="a", metadata={"source": "b.pdf", "page_number": 1}),
        Document(page_content="b", metadata={"source": "a.pdf", "page_number": 1}),
    ]

    assert build_citations(docs) == [
        {"source": "b.pdf", "page": 1},
        {"source": "a.pdf", "page": 1},
    ]


def test_different_pages_of_same_source_are_distinct_citations():
    docs = [
        Document(page_content="a", metadata={"source": "paper.pdf", "page_number": 3}),
        Document(page_content="b", metadata={"source": "paper.pdf", "page_number": 4}),
    ]

    assert build_citations(docs) == [
        {"source": "paper.pdf", "page": 3},
        {"source": "paper.pdf", "page": 4},
    ]


def test_missing_source_falls_back_to_unknown():
    docs = [Document(page_content="a", metadata={"page_number": 1})]

    assert build_citations(docs) == [{"source": "unknown", "page": 1}]


def test_missing_page_number_is_none():
    docs = [Document(page_content="a", metadata={"source": "notes.txt"})]

    assert build_citations(docs) == [{"source": "notes.txt", "page": None}]
