"""
Tests for RAGService's "no FAISS index loaded yet" handling
(src/services/rag_service.py, src/retrieval/vectorstore.py). Covers the
case a fresh shared-volume deployment hits before any ingestion has run --
see docker-compose.yml's bootstrap-order comments and docs/05-roadmap.md.
"""

import pytest

from tests.conftest import make_resources
from src.services.rag_service import RAGService


@pytest.fixture
def rag_service_no_index(monkeypatch):
    resources = make_resources(retriever=None)
    monkeypatch.setattr("src.services.rag_service.build_resources", lambda: resources)
    monkeypatch.setattr("src.services.rag_service.build_workflow", lambda resources: object())
    return RAGService()


def test_ask_returns_clear_answer_instead_of_crashing(rag_service_no_index):
    answer = rag_service_no_index.ask("What is this document about?")
    assert isinstance(answer, str)
    assert "don't have any documents" in answer.lower()


def test_ask_with_return_state_gives_a_consistent_shape(rag_service_no_index):
    state = rag_service_no_index.ask("query", session_id="s1", return_state=True)
    assert state["status"] == "no_index"
    assert state["session_id"] == "s1"
    assert "answer" in state and state["answer"]


def test_no_session_created_for_a_short_circuited_query(rag_service_no_index):
    # Short-circuits before touching session memory at all -- no reason
    # to create bookkeeping for a query that was never actually answered.
    rag_service_no_index.ask("query", session_id="s1")
    assert "s1" not in rag_service_no_index._sessions


def test_reload_index_recovers_once_an_index_exists(rag_service_no_index, monkeypatch):
    from langchain_core.documents import Document
    from tests.conftest import FakeRetriever

    fake_vectorstore = object()
    monkeypatch.setattr(
        "src.services.rag_service.VectorStoreFactory.load", lambda embeddings: fake_vectorstore
    )
    monkeypatch.setattr(
        "src.services.rag_service.RetrieverFactory.build",
        lambda vectorstore: FakeRetriever([Document(page_content="x")]),
    )

    assert rag_service_no_index.resources.retriever is None
    rag_service_no_index.reload_index()
    assert rag_service_no_index.resources.retriever is not None


def test_reload_index_stays_in_no_index_mode_if_still_missing(rag_service_no_index, monkeypatch):
    monkeypatch.setattr(
        "src.services.rag_service.VectorStoreFactory.load", lambda embeddings: None
    )

    rag_service_no_index.reload_index()

    assert rag_service_no_index.resources.retriever is None
