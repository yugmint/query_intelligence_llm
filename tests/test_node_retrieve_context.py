"""
Tests for nodes/retrieve_context.py::retrieve_documents.
"""

from langchain_core.documents import Document

from tests.conftest import FakeRetriever, FakeVectorStore, make_resources

from src.retrieval.config import RERANK_CANDIDATES, RERANK_CANDIDATES_NUMERIC
from src.workflow.nodes.retrieve_context import retrieve_documents


def test_uses_rewritten_query_when_present():
    retriever = FakeRetriever([Document(page_content="chunk one")])
    state = {"query": "original query", "rewritten_query": "resolved query", "documents": []}

    retrieve_documents(state, make_resources(retriever=retriever))

    assert retriever.queries == ["resolved query"]


def test_falls_back_to_query_when_rewritten_query_missing():
    retriever = FakeRetriever([Document(page_content="chunk one")])
    state = {"query": "original query", "rewritten_query": "", "documents": []}

    retrieve_documents(state, make_resources(retriever=retriever))

    assert retriever.queries == ["original query"]


def test_context_joins_page_content_with_blank_line():
    docs = [Document(page_content="first chunk"), Document(page_content="second chunk")]
    retriever = FakeRetriever(docs)
    state = {"query": "q", "rewritten_query": "", "documents": []}

    result = retrieve_documents(state, make_resources(retriever=retriever))

    assert result["context"] == "first chunk\n\nsecond chunk"
    assert result["documents"] == docs


def test_no_matches_produces_empty_context():
    retriever = FakeRetriever([])
    state = {"query": "q", "rewritten_query": "", "documents": []}

    result = retrieve_documents(state, make_resources(retriever=retriever))

    assert result["documents"] == []
    assert result["context"] == ""


def test_no_filter_uses_retriever_not_vectorstore():
    """
    Regression guard for the default/far-more-common path: when
    metadata_filter is absent, behavior must stay exactly what it was
    before filtering existed -- resources.retriever.invoke(), never
    touching resources.vectorstore at all.
    """
    retriever = FakeRetriever([Document(page_content="chunk one")])
    vectorstore = FakeVectorStore([Document(page_content="should not be used")])
    state = {"query": "q", "rewritten_query": "", "metadata_filter": None, "documents": []}

    result = retrieve_documents(state, make_resources(retriever=retriever, vectorstore=vectorstore))

    assert retriever.queries == ["q"]
    assert vectorstore.calls == []
    assert result["documents"] == [Document(page_content="chunk one")]


def test_filter_present_uses_vectorstore_similarity_search():
    retriever = FakeRetriever([Document(page_content="should not be used")])
    docs = [Document(page_content="filtered chunk")]
    vectorstore = FakeVectorStore(docs)
    metadata_filter = {"source": "EfficientNet.pdf"}
    state = {
        "query": "original query",
        "rewritten_query": "resolved query",
        "metadata_filter": metadata_filter,
        "documents": [],
    }

    result = retrieve_documents(
        state, make_resources(retriever=retriever, vectorstore=vectorstore)
    )

    assert retriever.queries == []
    assert vectorstore.calls == [
        {"query": "resolved query", "k": RERANK_CANDIDATES, "filter": metadata_filter}
    ]
    assert result["documents"] == docs
    assert result["context"] == "filtered chunk"


def test_no_filter_no_numeric_question_flag_is_false():
    retriever = FakeRetriever([Document(page_content="x")])
    state = {"query": "What is factor analysis?", "rewritten_query": "", "documents": []}

    result = retrieve_documents(state, make_resources(retriever=retriever))

    assert result["is_numeric_question"] is False


def test_numeric_question_widens_candidate_pool_via_vectorstore():
    """
    Regression guard for the distractor-number ranking gap (see
    docs/05-roadmap.md v0.2.0): a numeric question needs a wider
    candidate pool than the pre-built retriever's fixed k allows, so it
    must go through the same direct-vectorstore path as a metadata
    filter, using RERANK_CANDIDATES_NUMERIC instead of RERANK_CANDIDATES.
    """
    retriever = FakeRetriever([Document(page_content="should not be used")])
    docs = [Document(page_content="the correct numeric chunk")]
    vectorstore = FakeVectorStore(docs)
    state = {
        "query": "What was the sample size in this study?",
        "rewritten_query": "",
        "metadata_filter": None,
        "documents": [],
    }

    result = retrieve_documents(
        state, make_resources(retriever=retriever, vectorstore=vectorstore)
    )

    assert retriever.queries == []
    assert vectorstore.calls == [
        {
            "query": "What was the sample size in this study?",
            "k": RERANK_CANDIDATES_NUMERIC,
            "filter": None,
        }
    ]
    assert result["documents"] == docs
    assert result["is_numeric_question"] is True


def test_numeric_question_combined_with_metadata_filter():
    # Both widen the candidate pool AND apply the source filter -- the
    # two mechanisms aren't mutually exclusive.
    vectorstore = FakeVectorStore([Document(page_content="x")])
    metadata_filter = {"source": "airlock.pdf"}
    state = {
        "query": "How many patients were enrolled?",
        "rewritten_query": "",
        "metadata_filter": metadata_filter,
        "documents": [],
    }

    retrieve_documents(state, make_resources(vectorstore=vectorstore))

    assert vectorstore.calls == [
        {
            "query": "How many patients were enrolled?",
            "k": RERANK_CANDIDATES_NUMERIC,
            "filter": metadata_filter,
        }
    ]


def test_hybrid_search_fuses_dense_and_bm25_when_available():
    """
    Regression guard for hybrid search: the plain (no filter, no
    numeric) path should query BOTH retrievers and fuse via RRF, not
    silently drop back to dense-only, when a bm25_retriever is present.
    """
    shared = Document(page_content="shared chunk")
    dense_only = Document(page_content="dense only chunk")
    bm25_only = Document(page_content="bm25 only chunk")
    retriever = FakeRetriever([shared, dense_only])
    bm25_retriever = FakeRetriever([shared, bm25_only])
    state = {"query": "q", "rewritten_query": "", "metadata_filter": None, "documents": []}

    result = retrieve_documents(
        state, make_resources(retriever=retriever, bm25_retriever=bm25_retriever)
    )

    assert retriever.queries == ["q"]
    assert bm25_retriever.queries == ["q"]
    # The chunk both retrievers agree on should be fused to the front.
    assert result["documents"][0] == shared
    assert {d.page_content for d in result["documents"]} == {
        "shared chunk",
        "dense only chunk",
        "bm25 only chunk",
    }


def test_no_bm25_retriever_falls_back_to_dense_only():
    # bm25_retriever is None (e.g. resources built without an index at
    # startup) -- must behave exactly like the pre-hybrid-search path,
    # not crash trying to call it.
    retriever = FakeRetriever([Document(page_content="dense chunk")])
    state = {"query": "q", "rewritten_query": "", "metadata_filter": None, "documents": []}

    result = retrieve_documents(
        state, make_resources(retriever=retriever, bm25_retriever=None)
    )

    assert result["documents"] == [Document(page_content="dense chunk")]


def test_metadata_filter_does_not_invoke_bm25():
    # Hybrid search is deliberately scoped to the plain path -- a
    # metadata-filtered query must not touch BM25 at all.
    vectorstore = FakeVectorStore([Document(page_content="filtered chunk")])
    bm25_retriever = FakeRetriever([Document(page_content="should not be used")])
    state = {
        "query": "q",
        "rewritten_query": "",
        "metadata_filter": {"source": "x.pdf"},
        "documents": [],
    }

    retrieve_documents(
        state, make_resources(vectorstore=vectorstore, bm25_retriever=bm25_retriever)
    )

    assert bm25_retriever.queries == []


def test_numeric_question_does_not_invoke_bm25():
    # Same scoping decision as the filter case -- the numeric-question
    # widening targets a semantic-recall gap BM25 wouldn't help with
    # (see nodes/retrieve_context.py's comment on this).
    vectorstore = FakeVectorStore([Document(page_content="x")])
    bm25_retriever = FakeRetriever([Document(page_content="should not be used")])
    state = {
        "query": "What was the sample size in this study?",
        "rewritten_query": "",
        "metadata_filter": None,
        "documents": [],
    }

    retrieve_documents(
        state, make_resources(vectorstore=vectorstore, bm25_retriever=bm25_retriever)
    )

    assert bm25_retriever.queries == []
