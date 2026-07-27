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
