"""
Tests for src/utils/decorators.py::log_node -- specifically its
Prometheus metrics recording (src/utils/metrics.py), the single hook
point instrumenting every LangGraph node.

Each test uses a unique node_name so tests sharing the module-level
default Prometheus registry (the same one /metrics scrapes in
production) can't contaminate each other's counts within a test run.
"""

import pytest
from prometheus_client import generate_latest

from src.utils.decorators import log_node
from src.utils.metrics import NODE_DURATION_SECONDS, NODE_FAILURES_TOTAL


def _metrics_text() -> str:
    return generate_latest().decode()


def test_success_records_duration_but_not_a_failure():
    @log_node("test_node_success")
    def node(state, resources):
        return {"ok": True}

    node({}, None)

    text = _metrics_text()
    assert 'rag_node_duration_seconds_count{node="test_node_success"} 1.0' in text
    assert 'rag_node_failures_total{node="test_node_success"}' not in text


def test_failure_records_both_duration_and_failure_count():
    @log_node("test_node_failure")
    def node(state, resources):
        raise ValueError("boom")

    with pytest.raises(ValueError):
        node({}, None)

    text = _metrics_text()
    assert 'rag_node_duration_seconds_count{node="test_node_failure"} 1.0' in text
    assert 'rag_node_failures_total{node="test_node_failure"} 1.0' in text


def test_multiple_calls_accumulate():
    @log_node("test_node_multi")
    def node(state, resources):
        return {}

    node({}, None)
    node({}, None)
    node({}, None)

    text = _metrics_text()
    assert 'rag_node_duration_seconds_count{node="test_node_multi"} 3.0' in text


def test_different_nodes_tracked_independently():
    @log_node("test_node_a")
    def node_a(state, resources):
        return {}

    @log_node("test_node_b")
    def node_b(state, resources):
        raise RuntimeError("fail")

    node_a({}, None)
    with pytest.raises(RuntimeError):
        node_b({}, None)

    text = _metrics_text()
    assert 'rag_node_duration_seconds_count{node="test_node_a"} 1.0' in text
    assert 'rag_node_failures_total{node="test_node_a"}' not in text
    assert 'rag_node_duration_seconds_count{node="test_node_b"} 1.0' in text
    assert 'rag_node_failures_total{node="test_node_b"} 1.0' in text


def test_return_value_and_args_pass_through_unchanged():
    @log_node("test_node_passthrough")
    def node(state, resources):
        return {"documents": [state, resources]}

    result = node("state-value", "resources-value")

    assert result == {"documents": ["state-value", "resources-value"]}
