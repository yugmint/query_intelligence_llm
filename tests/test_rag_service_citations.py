"""
Tests for RAGService.ask()'s citation plumbing (src/services/rag_service.py):
citations are derived from whatever documents the workflow actually
returned, added onto the result before it's handed back -- see
src/services/citations.py for what a citation actually represents.
"""

import pytest
from langchain_core.documents import Document

from tests.conftest import FakeRetriever, make_resources
from src.services.rag_service import RAGService


class RecordingWorkflow:
    """Stand-in for the compiled LangGraph workflow -- returns a scripted result."""

    def __init__(self, result=None):
        self.invocations: list[dict] = []
        self._result = result if result is not None else {"answer": "the answer", "documents": []}

    def invoke(self, initial_state):
        self.invocations.append(initial_state)
        return self._result


def _service_with_workflow(monkeypatch, workflow):
    resources = make_resources(retriever=FakeRetriever([Document(page_content="x")]))
    monkeypatch.setattr("src.services.rag_service.build_resources", lambda: resources)
    monkeypatch.setattr("src.services.rag_service.build_workflow", lambda resources: workflow)
    return RAGService()


def test_citations_derived_from_returned_documents(monkeypatch):
    documents = [
        Document(page_content="a", metadata={"source": "paper.pdf", "page_number": 3}),
    ]
    workflow = RecordingWorkflow({"answer": "the answer", "documents": documents})
    service = _service_with_workflow(monkeypatch, workflow)

    state = service.ask("query", session_id="s1", return_state=True)

    assert state["citations"] == [{"source": "paper.pdf", "page": 3}]


def test_no_documents_gives_empty_citations(monkeypatch):
    workflow = RecordingWorkflow({"answer": "conversational reply", "documents": []})
    service = _service_with_workflow(monkeypatch, workflow)

    state = service.ask("hello", session_id="s1", return_state=True)

    assert state["citations"] == []


def test_missing_documents_key_gives_empty_citations(monkeypatch):
    # A node returning a state dict with no "documents" key at all
    # shouldn't crash citation-building.
    workflow = RecordingWorkflow({"answer": "the answer"})
    service = _service_with_workflow(monkeypatch, workflow)

    state = service.ask("query", session_id="s1", return_state=True)

    assert state["citations"] == []


def test_citations_not_included_when_return_state_is_false(monkeypatch):
    documents = [Document(page_content="a", metadata={"source": "paper.pdf", "page_number": 1})]
    workflow = RecordingWorkflow({"answer": "the answer", "documents": documents})
    service = _service_with_workflow(monkeypatch, workflow)

    answer = service.ask("query", session_id="s1", return_state=False)

    assert answer == "the answer"  # unchanged contract -- just the answer string
