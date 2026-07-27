"""
Tests for src/retrieval/parent_context.py::expand_to_parent_context.
"""

from langchain_core.documents import Document

from src.retrieval.config import PARENT_CONTEXT_MAX_CHARS_PER_PAGE
from src.retrieval.parent_context import expand_to_parent_context


class _FakeDocstoreVectorStore:
    """Stand-in exposing .docstore._dict, the only thing this module reads."""

    def __init__(self, documents):
        from types import SimpleNamespace
        self.docstore = SimpleNamespace(_dict={str(i): d for i, d in enumerate(documents)})


def _doc(content, source="a.pdf", page=None):
    metadata = {"source": source}
    if page is not None:
        metadata["page_number"] = page
    return Document(page_content=content, metadata=metadata)


def test_no_vectorstore_falls_back_to_raw_join():
    documents = [_doc("chunk one"), _doc("chunk two")]

    result = expand_to_parent_context(documents, None)

    assert result == "chunk one\n\nchunk two"


def test_expands_to_full_page_text():
    corpus = [
        _doc("First part of page 1.", page=1),
        _doc("Second part of page 1.", page=1),
        _doc("Only part of page 2.", page=2),
    ]
    vectorstore = _FakeDocstoreVectorStore(corpus)
    matched = [corpus[0]]  # only the first chunk was actually retrieved/reranked

    result = expand_to_parent_context(matched, vectorstore)

    assert "First part of page 1." in result
    assert "Second part of page 1." in result  # pulled in as the parent


def test_two_matched_chunks_from_same_page_not_duplicated():
    corpus = [
        _doc("Part A.", page=1),
        _doc("Part B.", page=1),
    ]
    vectorstore = _FakeDocstoreVectorStore(corpus)
    matched = [corpus[0], corpus[1]]  # both chunks from the same page

    result = expand_to_parent_context(matched, vectorstore)

    assert result.count("Part A.") == 1
    assert result.count("Part B.") == 1


def test_chunks_without_page_number_use_own_content():
    corpus = [_doc("standalone text, no page concept")]
    vectorstore = _FakeDocstoreVectorStore(corpus)

    result = expand_to_parent_context(corpus, vectorstore)

    assert result == "standalone text, no page concept"


def test_different_sources_same_page_number_not_mixed():
    corpus = [
        _doc("Doc A page 1 content.", source="a.pdf", page=1),
        _doc("Doc B page 1 content.", source="b.pdf", page=1),
    ]
    vectorstore = _FakeDocstoreVectorStore(corpus)
    matched = [corpus[0]]

    result = expand_to_parent_context(matched, vectorstore)

    assert "Doc A page 1" in result
    assert "Doc B page 1" not in result


def test_oversized_page_falls_back_to_matched_chunk_only():
    # Regression guard for a real Groq 413 (TOP_K_NUMERIC=8 chunks each
    # expanding to a full dense page blew past the 6000 TPM ceiling).
    # A page over budget must fall back to the matched chunk, not an
    # arbitrary truncated slice that could cut out the relevant part.
    matched_chunk = _doc("the actually relevant matched sentence.", page=1)
    huge_neighbor = _doc("x" * (PARENT_CONTEXT_MAX_CHARS_PER_PAGE + 1), page=1)
    vectorstore = _FakeDocstoreVectorStore([matched_chunk, huge_neighbor])

    result = expand_to_parent_context([matched_chunk], vectorstore)

    assert result == "the actually relevant matched sentence."


def test_page_within_budget_still_expands():
    small_chunk = _doc("part one.", page=1)
    small_neighbor = _doc("part two.", page=1)
    vectorstore = _FakeDocstoreVectorStore([small_chunk, small_neighbor])

    result = expand_to_parent_context([small_chunk], vectorstore)

    assert "part one." in result
    assert "part two." in result
