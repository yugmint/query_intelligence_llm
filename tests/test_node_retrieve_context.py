"""
Tests for nodes/retrieve_context.py::retrieve_documents.
"""

from langchain_core.documents import Document

from tests.conftest import FakeRetriever, FakeVectorStore, make_resources

from src.retrieval.config import RERANK_CANDIDATES
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
