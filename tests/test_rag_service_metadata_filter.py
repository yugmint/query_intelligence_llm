"""
Tests for RAGService's metadata-filter plumbing (src/services/rag_service.py):
- ask()'s metadata_filter parameter reaching the workflow's initial_state
  unchanged
- list_sources(), which exists so a caller can discover valid filter
  values before guessing at a source filename (see GET /sources in
  src/api.py)
"""

from types import SimpleNamespace

import pytest
from langchain_core.documents import Document

from tests.conftest import FakeRetriever, make_resources
from src.services.rag_service import RAGService


class RecordingWorkflow:
    """
    Stand-in for the compiled LangGraph workflow. Records the initial_state
    it was invoked with and returns a scripted result -- lets ask() tests
    assert on what actually reached the workflow without running any real
    node.
    """

    def __init__(self, result=None):
        self.invocations: list[dict] = []
        self._result = result or {"answer": "the answer", "status": "ok"}

    def invoke(self, initial_state):
        self.invocations.append(initial_state)
        return self._result


@pytest.fixture
def rag_service_with_index(monkeypatch):
    """
    A RAGService with a non-None retriever (so ask() takes the normal
    workflow path, not the no-index short-circuit) and a RecordingWorkflow
    in place of the real compiled graph.
    """
    resources = make_resources(retriever=FakeRetriever([Document(page_content="x")]))
    workflow = RecordingWorkflow()
    monkeypatch.setattr("src.services.rag_service.build_resources", lambda: resources)
    monkeypatch.setattr("src.services.rag_service.build_workflow", lambda resources: workflow)
    return RAGService(), workflow


def test_ask_with_no_filter_passes_none_through(rag_service_with_index):
    service, workflow = rag_service_with_index

    service.ask("query", session_id="s1")

    assert workflow.invocations[0]["metadata_filter"] is None


def test_ask_threads_metadata_filter_into_initial_state(rag_service_with_index):
    service, workflow = rag_service_with_index
    metadata_filter = {"source": "EfficientNet.pdf"}

    service.ask("query", session_id="s1", metadata_filter=metadata_filter)

    assert workflow.invocations[0]["metadata_filter"] == metadata_filter


class FakeVectorStoreWithDocstore:
    """
    Stand-in for the parts of langchain_community.vectorstores.FAISS that
    list_sources() actually touches: docstore._dict, a plain dict of
    id -> Document. Real FAISS has no public "list all documents" API,
    so list_sources() reaches into this private attribute directly --
    matching that shape here is the point of this fake.
    """

    def __init__(self, documents: dict):
        self.docstore = SimpleNamespace(_dict=documents)


def test_list_sources_empty_index_returns_empty_list():
    resources = make_resources(vectorstore=None)
    service = RAGService.__new__(RAGService)
    service.resources = resources

    assert service.list_sources() == []


def test_list_sources_aggregates_counts_per_source_sorted():
    documents = {
        "1": Document(page_content="a", metadata={"source": "b.pdf", "document_type": "research_paper"}),
        "2": Document(page_content="b", metadata={"source": "a.pdf", "document_type": "book"}),
        "3": Document(page_content="c", metadata={"source": "b.pdf", "document_type": "research_paper"}),
    }
    resources = make_resources(vectorstore=FakeVectorStoreWithDocstore(documents))
    service = RAGService.__new__(RAGService)
    service.resources = resources

    result = service.list_sources()

    assert result == [
        {"source": "a.pdf", "document_type": "book", "chunk_count": 1},
        {"source": "b.pdf", "document_type": "research_paper", "chunk_count": 2},
    ]


def test_list_sources_missing_source_metadata_falls_back_to_unknown():
    documents = {"1": Document(page_content="a", metadata={})}
    resources = make_resources(vectorstore=FakeVectorStoreWithDocstore(documents))
    service = RAGService.__new__(RAGService)
    service.resources = resources

    result = service.list_sources()

    assert result == [{"source": "unknown", "document_type": None, "chunk_count": 1}]
