"""
Tests for src/retrieval/parent_context.py::expand_to_parent_context.
"""

from types import SimpleNamespace

from langchain_core.documents import Document

from src.retrieval.config import PARENT_CONTEXT_NEIGHBOR_CHUNKS
from src.retrieval.parent_context import expand_to_parent_context


class _FakeDocstoreVectorStore:
    """Stand-in exposing .docstore._dict, the only thing this module reads."""

    def __init__(self, documents):
        self.docstore = SimpleNamespace(_dict={str(i): d for i, d in enumerate(documents)})


def _doc(content, source="a.pdf", chunk_id=None):
    metadata = {"source": source}
    if chunk_id is not None:
        metadata["chunk_id"] = chunk_id
    return Document(page_content=content, metadata=metadata)


def _corpus(*contents, source="a.pdf"):
    return [_doc(c, source=source, chunk_id=i) for i, c in enumerate(contents)]


def test_no_vectorstore_falls_back_to_raw_join():
    documents = [_doc("chunk one"), _doc("chunk two")]

    result = expand_to_parent_context(documents, None)

    assert result == "chunk one\n\nchunk two"


def test_expands_to_neighbors_by_chunk_id():
    corpus = _corpus("before.", "MATCHED.", "after.")
    vectorstore = _FakeDocstoreVectorStore(corpus)
    matched = [corpus[1]]  # chunk_id 1, neighbors at 0 and 2 (default window=1)

    result = expand_to_parent_context(matched, vectorstore)

    assert "before." in result
    assert "MATCHED." in result
    assert "after." in result


def test_neighbor_window_does_not_cross_source_boundary():
    doc_a = _doc("last chunk of doc A.", source="a.pdf", chunk_id=5)
    doc_b_before = _doc("would-be neighbor in doc B.", source="b.pdf", chunk_id=4)
    vectorstore = _FakeDocstoreVectorStore([doc_a, doc_b_before])

    result = expand_to_parent_context([doc_a], vectorstore)

    assert "last chunk of doc A." in result
    assert "would-be neighbor in doc B." not in result


def test_overlapping_windows_from_two_matches_not_duplicated():
    corpus = _corpus("c0.", "c1.", "c2.", "c3.", "c4.")
    vectorstore = _FakeDocstoreVectorStore(corpus)
    # chunk_id 1 and chunk_id 3 both matched -- their window=1 neighbors
    # overlap at chunk_id 2.
    matched = [corpus[1], corpus[3]]

    result = expand_to_parent_context(matched, vectorstore)

    assert result.count("c2.") == 1
    for expected in ["c0.", "c1.", "c2.", "c3.", "c4."]:
        assert expected in result


def test_non_contiguous_matches_produce_separate_paragraphs():
    corpus = _corpus(*[f"c{i}." for i in range(10)])
    vectorstore = _FakeDocstoreVectorStore(corpus)
    # chunk_id 1 and chunk_id 8 are far apart -- their windows don't touch.
    matched = [corpus[1], corpus[8]]

    result = expand_to_parent_context(matched, vectorstore)

    parts = result.split("\n\n")
    assert len(parts) == 2
    assert "c0." in parts[0] and "c1." in parts[0] and "c2." in parts[0]
    assert "c7." in parts[1] and "c8." in parts[1] and "c9." in parts[1]


def test_chunks_without_chunk_id_use_own_content():
    doc = _doc("standalone text, no chunk_id")
    vectorstore = _FakeDocstoreVectorStore([doc])

    result = expand_to_parent_context([doc], vectorstore)

    assert result == "standalone text, no chunk_id"


def test_window_size_is_configurable_and_bounded():
    # Regression guard for the real 413 that motivated bounding by
    # count: a wide-ranging match set should never pull in the whole
    # corpus, only PARENT_CONTEXT_NEIGHBOR_CHUNKS on each side.
    corpus = _corpus(*[f"c{i}." for i in range(50)])
    vectorstore = _FakeDocstoreVectorStore(corpus)
    matched = [corpus[25]]

    result = expand_to_parent_context(matched, vectorstore)

    expected_count = 2 * PARENT_CONTEXT_NEIGHBOR_CHUNKS + 1
    assert sum(result.count(f"c{i}.") for i in range(50)) == expected_count
