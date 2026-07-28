# src/utils/metrics.py

"""
Prometheus metrics for this service -- the "observability" half of
docs/05-roadmap.md v0.5.0 (structured logs already existed; this is
what's queryable/graphable over time instead of grepped after the
fact).

Deliberately a small, fixed set of metrics rather than instrumenting
everything: node-level latency/failures (the actual question anyone
debugging a slow or failing query will ask -- "which node?") and
request-level outcomes, not a metric for every internal function.
"""

from prometheus_client import Counter, Gauge, Histogram

# Per-LangGraph-node timing, recorded once per node execution by
# src/utils/decorators.py::log_node -- every node already goes through
# that decorator, so this is a single hook point rather than
# instrumenting each of the 8 node files individually. Recorded on both
# success and failure (a node that's slow right before it fails is
# still a useful latency signal, e.g. a timeout).
NODE_DURATION_SECONDS = Histogram(
    "rag_node_duration_seconds",
    "Time spent executing each LangGraph node.",
    ["node"],
)

NODE_FAILURES_TOTAL = Counter(
    "rag_node_failures_total",
    "Node executions that raised an exception.",
    ["node"],
)

# Request-level outcome, recorded once per /query or /query/stream call
# in src/api.py. outcome is one of: "success" (a normal answer),
# "rejected" (input guardrail blocked it), "no_index" (no FAISS index
# loaded yet), "error" (an unhandled exception -- the 503/in-band-error
# path).
REQUESTS_TOTAL = Counter(
    "rag_requests_total",
    "Query requests, by endpoint and outcome.",
    ["endpoint", "outcome"],
)

# Set at scrape time (GET /metrics) rather than incrementally, since
# it's a point-in-time count already available via
# len(RAGService._sessions) -- no need to track it as a running total.
ACTIVE_SESSIONS = Gauge(
    "rag_active_sessions",
    "Current number of in-memory conversation sessions.",
)

RESPONSE_CACHE_ENTRIES = Gauge(
    "rag_response_cache_entries",
    "Current number of entries in the response cache.",
)

# The actual point of the cache (see docs/05-roadmap.md v0.6.0, token
# efficiency) -- a hit means a whole workflow invocation (embedding +
# retrieval + at least one LLM call) was skipped entirely.
RESPONSE_CACHE_HITS_TOTAL = Counter(
    "rag_response_cache_hits_total",
    "Response cache hits -- each one is a full workflow invocation skipped.",
)


def outcome_for_state(state: dict) -> str:
    """
    Maps a completed query's final state to one of REQUESTS_TOTAL's
    outcome labels. Shared by /query and /query/stream so both endpoints
    classify identically.
    """

    status = state.get("status", "")

    if status == "rejected":
        return "rejected"
    if status == "no_index":
        return "no_index"

    return "success"
