"""
Tests for RAGService's response cache (src/services/rag_service.py) --
see docs/05-roadmap.md v0.6.0 (token efficiency). Reuses the
RecordingWorkflow pattern from test_rag_service_citations.py so a
"cache hit" can be verified as "workflow.invoke() was NOT called
again", not just "same answer came back".
"""

from langchain_core.documents import Document

from tests.conftest import FakeRetriever, make_resources
from src.services.rag_service import RAGService


class RecordingWorkflow:
    def __init__(self, result=None):
        self.invocations: list[dict] = []
        self._result = result if result is not None else {"answer": "the answer", "documents": []}

    def invoke(self, initial_state):
        self.invocations.append(initial_state)
        return dict(self._result)


def _service_with_workflow(monkeypatch, workflow):
    resources = make_resources(retriever=FakeRetriever([Document(page_content="x")]))
    monkeypatch.setattr("src.services.rag_service.build_resources", lambda: resources)
    monkeypatch.setattr("src.services.rag_service.build_workflow", lambda resources: workflow)
    return RAGService()


def test_repeated_first_turn_question_hits_cache_not_workflow(monkeypatch):
    workflow = RecordingWorkflow({"answer": "42", "documents": []})
    service = _service_with_workflow(monkeypatch, workflow)

    first = service.ask("what is the answer?", session_id="s1")
    second = service.ask("what is the answer?", session_id="s2")  # different session, same Q

    assert first == second == "42"
    assert len(workflow.invocations) == 1  # second call never reached the workflow


def test_query_normalization_matters_for_cache_key(monkeypatch):
    workflow = RecordingWorkflow({"answer": "42", "documents": []})
    service = _service_with_workflow(monkeypatch, workflow)

    service.ask("What Is The Answer?  ", session_id="s1")
    service.ask("what is the answer?", session_id="s2")

    assert len(workflow.invocations) == 1  # case/whitespace-insensitive hit


def test_mid_conversation_question_is_never_cached(monkeypatch):
    # RecordingWorkflow doesn't run the real update_memory node, so seed
    # session "s1"'s history directly to simulate an ongoing conversation.
    workflow = RecordingWorkflow({"answer": "42", "documents": []})
    service = _service_with_workflow(monkeypatch, workflow)
    memory = service._get_session_memory("s1")
    memory.add_user_message("earlier question")
    memory.add_ai_message("earlier answer")

    service.ask("what is the answer?", session_id="s1")  # has chat_history -- not cacheable
    service.ask("what is the answer?", session_id="s2")  # fresh session, same text -- still a miss

    assert len(workflow.invocations) == 2


def test_different_metadata_filter_is_a_cache_miss(monkeypatch):
    workflow = RecordingWorkflow({"answer": "42", "documents": []})
    service = _service_with_workflow(monkeypatch, workflow)

    service.ask("q", session_id="s1", metadata_filter={"source": "a.pdf"})
    service.ask("q", session_id="s2", metadata_filter={"source": "b.pdf"})

    assert len(workflow.invocations) == 2


def test_cache_hit_still_updates_the_asking_sessions_memory(monkeypatch):
    workflow = RecordingWorkflow({"answer": "42", "documents": []})
    service = _service_with_workflow(monkeypatch, workflow)

    service.ask("what is the answer?", session_id="s1")
    service.ask("what is the answer?", session_id="s2")

    memory = service._get_session_memory("s2")
    assert [m.content for m in memory.messages] == ["what is the answer?", "42"]


def test_cache_hit_does_not_leak_another_sessions_identity(monkeypatch):
    workflow = RecordingWorkflow({"answer": "42", "documents": []})
    service = _service_with_workflow(monkeypatch, workflow)

    service.ask("what is the answer?", session_id="s1", return_state=True)
    state = service.ask("what is the answer?", session_id="s2", return_state=True)

    assert state["session_id"] == "s2"
    assert state["session_memory"] is service._get_session_memory("s2")


def test_reload_index_clears_the_cache(monkeypatch):
    workflow = RecordingWorkflow({"answer": "42", "documents": []})
    service = _service_with_workflow(monkeypatch, workflow)
    monkeypatch.setattr("src.services.rag_service.VectorStoreFactory.load", lambda embeddings: None)

    service.ask("what is the answer?", session_id="s1")
    assert service.cached_response_count() == 1

    service.reload_index()

    assert service.cached_response_count() == 0


def test_cached_response_count_matches_cache_size(monkeypatch):
    workflow = RecordingWorkflow({"answer": "42", "documents": []})
    service = _service_with_workflow(monkeypatch, workflow)

    assert service.cached_response_count() == 0
    service.ask("q1", session_id="s1")
    service.ask("q2", session_id="s2")
    assert service.cached_response_count() == 2


def test_cache_bounded_and_lru_evicted(monkeypatch):
    workflow = RecordingWorkflow({"answer": "42", "documents": []})
    service = _service_with_workflow(monkeypatch, workflow)
    monkeypatch.setattr("src.services.rag_service.MAX_CACHE_ENTRIES", 2)

    service.ask("q1", session_id="s1")
    service.ask("q2", session_id="s2")
    service.ask("q3", session_id="s3")  # evicts q1

    assert service.cached_response_count() == 2
    workflow.invocations.clear()
    service.ask("q1", session_id="s4")  # miss, was evicted
    assert len(workflow.invocations) == 1
