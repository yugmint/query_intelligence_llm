"""
Tests for RAGService.ask_stream() (src/services/rag_service.py):
token-level streaming via the compiled graph's own
stream_mode=["messages", "values"], filtered so only user-facing nodes'
output reaches the caller, with citations/intent/status delivered once
in a final "done" event.
"""

from types import SimpleNamespace

import pytest
from langchain_core.documents import Document

from tests.conftest import FakeRetriever, make_resources
from src.services.rag_service import RAGService


class RecordingStreamingWorkflow:
    """
    Stand-in for the compiled LangGraph workflow's .stream() method.
    `events` is a list of (node_name, content) pairs emulating the
    "messages" stream_mode's yielded (chunk, metadata) pairs; a single
    "values" event carrying `final_values` is always yielded last,
    matching how the real graph's last "values" payload is the complete
    final state.
    """

    def __init__(self, events, final_values=None):
        self.events = events
        self.final_values = final_values if final_values is not None else {
            "answer": "",
            "documents": [],
        }
        self.invocations: list[dict] = []

    def stream(self, initial_state, stream_mode=None):
        self.invocations.append(initial_state)
        for node, content in self.events:
            yield ("messages", (SimpleNamespace(content=content), {"langgraph_node": node}))
        yield ("values", self.final_values)


def _service_with_workflow(monkeypatch, workflow):
    resources = make_resources(retriever=FakeRetriever([Document(page_content="x")]))
    monkeypatch.setattr("src.services.rag_service.build_resources", lambda: resources)
    monkeypatch.setattr("src.services.rag_service.build_workflow", lambda resources: workflow)
    return RAGService()


def test_generate_node_tokens_are_forwarded_in_order(monkeypatch):
    workflow = RecordingStreamingWorkflow(
        events=[("generate", "Hello"), ("generate", " world")],
        final_values={"answer": "Hello world", "documents": []},
    )
    service = _service_with_workflow(monkeypatch, workflow)

    events = list(service.ask_stream("query", session_id="s1"))

    tokens = [e for e in events if e["type"] == "token"]
    assert [t["content"] for t in tokens] == ["Hello", " world"]


def test_conversation_branch_tokens_forwarded(monkeypatch):
    workflow = RecordingStreamingWorkflow(
        events=[("conversation", "Hey"), ("conversation", " there!")],
        final_values={"answer": "Hey there!", "documents": []},
    )
    service = _service_with_workflow(monkeypatch, workflow)

    events = list(service.ask_stream("hi", session_id="s1"))

    tokens = [e for e in events if e["type"] == "token"]
    assert [t["content"] for t in tokens] == ["Hey", " there!"]


def test_non_user_facing_node_tokens_are_filtered_out(monkeypatch):
    # detect_intent's raw classification JSON must never reach the caller.
    workflow = RecordingStreamingWorkflow(
        events=[
            ("detect_intent", '{"intent": "knowledge"}'),
            ("generate", "The answer."),
        ],
        final_values={"answer": "The answer.", "documents": []},
    )
    service = _service_with_workflow(monkeypatch, workflow)

    events = list(service.ask_stream("query", session_id="s1"))

    tokens = [e for e in events if e["type"] == "token"]
    assert [t["content"] for t in tokens] == ["The answer."]


def test_exactly_one_done_event_with_final_state(monkeypatch):
    documents = [Document(page_content="a", metadata={"source": "paper.pdf", "page_number": 5})]
    workflow = RecordingStreamingWorkflow(
        events=[("generate", "answer text")],
        final_values={
            "answer": "answer text",
            "intent": "knowledge",
            "status": "ok",
            "documents": documents,
        },
    )
    service = _service_with_workflow(monkeypatch, workflow)

    events = list(service.ask_stream("query", session_id="s1"))

    done_events = [e for e in events if e["type"] == "done"]
    assert len(done_events) == 1
    done = done_events[0]
    assert done["answer"] == "answer text"
    assert done["intent"] == "knowledge"
    assert done["status"] == "ok"
    assert done["session_id"] == "s1"
    assert done["citations"] == [{"source": "paper.pdf", "page": 5}]
    # done must be the last event -- nothing should be yielded after it.
    assert events[-1] is done


def test_no_index_yields_single_done_event_no_tokens(monkeypatch):
    resources = make_resources(retriever=None)
    monkeypatch.setattr("src.services.rag_service.build_resources", lambda: resources)
    monkeypatch.setattr("src.services.rag_service.build_workflow", lambda resources: object())
    service = RAGService()

    events = list(service.ask_stream("query", session_id="s1"))

    assert len(events) == 1
    assert events[0]["type"] == "done"
    assert events[0]["status"] == "no_index"
    assert events[0]["citations"] == []
    assert "don't have any documents" in events[0]["answer"].lower()


def test_tokens_with_empty_content_are_not_forwarded(monkeypatch):
    # Some chunks (e.g. the first one of a streamed response) can carry
    # empty content -- shouldn't produce a no-op token event.
    workflow = RecordingStreamingWorkflow(
        events=[("generate", ""), ("generate", "real content")],
        final_values={"answer": "real content", "documents": []},
    )
    service = _service_with_workflow(monkeypatch, workflow)

    events = list(service.ask_stream("query", session_id="s1"))

    tokens = [e for e in events if e["type"] == "token"]
    assert [t["content"] for t in tokens] == ["real content"]
