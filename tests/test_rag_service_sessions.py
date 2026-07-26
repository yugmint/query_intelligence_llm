"""
Tests for RAGService's session store bounding/eviction
(src/services/rag_service.py). Patches out build_resources/build_workflow
(real embedding/LLM/graph construction) since only the session-bookkeeping
methods are under test here -- everything else is exercised via the node
tests and workflow.py directly.
"""

import pytest

from src.services.rag_service import RAGService


@pytest.fixture
def rag_service(monkeypatch):
    monkeypatch.setattr("src.services.rag_service.build_resources", lambda: object())
    monkeypatch.setattr("src.services.rag_service.build_workflow", lambda resources: object())
    return RAGService()


def test_new_sessions_are_created_lazily(rag_service):
    assert len(rag_service._sessions) == 0
    rag_service._get_session_memory("alice")
    assert len(rag_service._sessions) == 1
    assert "alice" in rag_service._sessions


def test_same_session_id_reuses_existing_memory(rag_service):
    first = rag_service._get_session_memory("alice")
    second = rag_service._get_session_memory("alice")
    assert first is second
    assert len(rag_service._sessions) == 1


def test_store_evicts_least_recently_used_when_full(rag_service, monkeypatch):
    monkeypatch.setattr("src.services.rag_service.MAX_SESSIONS", 2)

    rag_service._get_session_memory("a")
    rag_service._get_session_memory("b")
    rag_service._get_session_memory("c")  # store full at "a","b" -> evicts "a"

    assert "a" not in rag_service._sessions
    assert "b" in rag_service._sessions
    assert "c" in rag_service._sessions
    assert len(rag_service._sessions) == 2


def test_accessing_a_session_protects_it_from_eviction(rag_service, monkeypatch):
    monkeypatch.setattr("src.services.rag_service.MAX_SESSIONS", 2)

    rag_service._get_session_memory("a")
    rag_service._get_session_memory("b")
    rag_service._get_session_memory("a")  # touch "a" -- now "b" is the LRU one
    rag_service._get_session_memory("c")  # should evict "b", not "a"

    assert "a" in rag_service._sessions
    assert "b" not in rag_service._sessions
    assert "c" in rag_service._sessions


def test_reset_memory_does_not_bypass_the_bound(rag_service, monkeypatch):
    monkeypatch.setattr("src.services.rag_service.MAX_SESSIONS", 2)

    rag_service._get_session_memory("a")
    rag_service._get_session_memory("b")
    rag_service.reset_memory("c")  # new session via reset_memory -- still bounded

    assert len(rag_service._sessions) == 2
    assert "a" not in rag_service._sessions  # "a" was the LRU entry, evicted
    assert "c" in rag_service._sessions


def test_reset_memory_on_existing_session_replaces_without_growing_store(rag_service):
    first = rag_service._get_session_memory("a")
    rag_service.reset_memory("a")
    second = rag_service._get_session_memory("a")

    assert len(rag_service._sessions) == 1
    assert first is not second  # actually reset, not the same object
