# src/api.py

"""
FastAPI service exposing the RAG workflow over HTTP.

Additive deployment mode: `main.py`'s interactive CLI still works
unchanged. This is meant to run as a standalone service, paired with
the separate `ingestion_fixed` project's own API, sharing one FAISS
index directory (e.g. a mounted volume). See DOCUMENTATION.md for the
full deployment pattern.

Conversation memory is scoped per `session_id` (pass one in the request
body; omit it to share the one implicit default session). Concurrent
requests for *different* session_ids are isolated from each other.
Still not a complete production answer: the session store is an
in-memory dict with no persistence and no eviction (see
`src/services/rag_service.py` and docs/05-roadmap.md) -- fine for
dev/demo/moderate traffic, not yet for long-running high-volume
multi-user production use.
"""

import json
import os

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from src.services.rag_service import DEFAULT_SESSION_ID, RAGService
from src.utils.auth import require_api_key
from src.utils.logger import logger
from src.utils.metrics import ACTIVE_SESSIONS, REQUESTS_TOTAL, outcome_for_state

app = FastAPI(title="RAG Query API", version="0.1.0")

# Without this, browsers silently block every request from any frontend
# not served from this exact origin -- including a `file://`-opened
# local HTML page (see ../frontend), which is the primary local-testing
# client this API needs to support. Defaults wide open, matching that
# use case; API-key auth (above/below) is the actual access-control
# layer once APP_ENV is set to anything other than "development" -- CORS
# alone was never meant to be that. Override via CORS_ALLOW_ORIGINS
# (comma-separated) for a real deployment that wants to restrict this.
_cors_origins = os.getenv("CORS_ALLOW_ORIGINS", "*")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if _cors_origins == "*" else _cors_origins.split(","),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Per-client (by IP) rate limiting, in addition to the global client-side
# throttle already on the LLM calls themselves (src/retrieval/llm.py) --
# different layer, same goal. That LLM-level throttle protects the shared
# Groq quota from the *aggregate* of all clients; this protects the
# service itself from any *single* client hammering it with requests
# that never even reach the LLM (e.g. empty/near-empty queries that still
# cost a guardrail + retrieval pass). In-memory storage (the default,
# no `storage_uri` set) is fine for a single-process deployment; would
# need a shared backend (e.g. Redis) for multi-instance deployments --
# not needed at current scale. See docs/05-roadmap.md.
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

rag = RAGService()


class QueryRequest(BaseModel):
    query: str
    session_id: str = DEFAULT_SESSION_ID
    # Scopes this query to one previously-ingested document instead of
    # searching the whole index -- matters now that ingestion is
    # additive (v0.4.0) and one index can hold several unrelated
    # documents. Matched against each chunk's "source" metadata
    # (the filename ingestion_fixed recorded it under); see GET
    # /sources for the actual values available to filter by. None
    # (default) searches everything, unchanged from before this existed.
    source: str | None = None


class Citation(BaseModel):
    source: str
    # None for sources without page-level metadata (ingestion_fixed's
    # PDFLoader sets it; other loaders may not).
    page: int | None = None


class QueryResponse(BaseModel):
    answer: str
    intent: str = ""
    status: str = ""
    session_id: str = DEFAULT_SESSION_ID
    # Chunk-provenance, not verified per-claim attribution -- what was
    # provided as context for this answer, not a guarantee every listed
    # source was actually drawn on in the final wording. See
    # src/services/citations.py.
    citations: list[Citation] = []


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/query", response_model=QueryResponse, dependencies=[Depends(require_api_key)])
@limiter.limit("10/minute")
def query(request: Request, body: QueryRequest):
    if not body.query or not body.query.strip():
        raise HTTPException(status_code=400, detail="query must not be empty")

    metadata_filter = {"source": body.source} if body.source else None

    try:
        state = rag.ask(
            body.query,
            session_id=body.session_id,
            return_state=True,
            metadata_filter=metadata_filter,
        )
    except Exception as exc:
        # The LLM call inside this workflow already retries transient
        # failures (LLMFactory's max_retries + client-side rate limiting --
        # see src/retrieval/llm.py); anything that still reaches here is
        # either a genuinely exhausted retry budget or an unrelated bug.
        # Either way, callers should see a clean 503, not an unhandled
        # exception's stack trace. Confirmed necessary by an actual crash
        # under concurrent load -- see
        # docs/reports/2026-07-26-performance-and-deployment-readiness.md.
        logger.error(f"Query failed for session '{body.session_id}': {exc}")
        REQUESTS_TOTAL.labels(endpoint="query", outcome="error").inc()
        raise HTTPException(
            status_code=503,
            detail="The assistant is temporarily unavailable. Please try again shortly.",
        ) from exc

    REQUESTS_TOTAL.labels(endpoint="query", outcome=outcome_for_state(state)).inc()

    return QueryResponse(
        answer=state.get("answer", ""),
        intent=state.get("intent", ""),
        status=state.get("status", ""),
        session_id=body.session_id,
        citations=state.get("citations", []),
    )


def _sse_event(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


@app.post("/query/stream", dependencies=[Depends(require_api_key)])
@limiter.limit("10/minute")
def query_stream(request: Request, body: QueryRequest):
    """
    Same as /query, but streams the answer incrementally as
    Server-Sent Events instead of waiting for the full answer before
    responding. Each event is `data: <json>\\n\\n`; the `type` field is
    either "token" ({"type": "token", "content": str}, one per piece of
    the answer as it's generated) or "done" (the same shape /query
    returns -- answer, intent, status, session_id, citations -- sent
    exactly once at the end) or "error" (see below).

    POST rather than GET/EventSource: the browser's native EventSource
    API is GET-only and can't carry a JSON body (query, session_id,
    source), so the frontend reads this via fetch() + a manual
    ReadableStream reader instead. See ../frontend/index.html.
    """
    if not body.query or not body.query.strip():
        raise HTTPException(status_code=400, detail="query must not be empty")

    metadata_filter = {"source": body.source} if body.source else None

    def event_stream():
        try:
            for event in rag.ask_stream(
                body.query,
                session_id=body.session_id,
                metadata_filter=metadata_filter,
            ):
                if event.get("type") == "done":
                    REQUESTS_TOTAL.labels(
                        endpoint="query_stream", outcome=outcome_for_state(event)
                    ).inc()
                yield _sse_event(event)
        except Exception as exc:
            # Once streaming has started, the response's 200 status is
            # already committed -- unlike /query, there's no way to
            # switch to a 503 at this point. Signal failure in-band
            # instead so the client sees a clean error event rather than
            # a silently truncated stream or a raw traceback. Same
            # underlying failure class /query's 503 handles -- see its
            # comment for why this can still happen despite the LLM
            # client's own retries.
            logger.error(f"Streaming query failed for session '{body.session_id}': {exc}")
            REQUESTS_TOTAL.labels(endpoint="query_stream", outcome="error").inc()
            yield _sse_event(
                {
                    "type": "error",
                    "detail": "The assistant is temporarily unavailable. Please try again shortly.",
                }
            )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@app.get("/metrics", dependencies=[Depends(require_api_key)])
def metrics():
    """
    Prometheus text-exposition format: per-node latency/failure counts
    (src/utils/decorators.py::log_node), request outcomes by endpoint,
    and the current active-session count. Point this at Prometheus/
    Grafana, or use ../frontend/dashboard.html for a built-in view that
    needs no extra infrastructure. Auth-protected like every other
    non-/health endpoint here -- these numbers reveal real traffic
    patterns, not something to expose to the public internet
    unauthenticated.
    """

    ACTIVE_SESSIONS.set(rag.active_session_count())

    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/sources", dependencies=[Depends(require_api_key)])
def sources():
    """
    Distinct documents currently in the index, with a chunk count each.
    Use a value from here as /query's `source` field to scope a
    question to one document instead of searching everything.
    """
    return {"sources": rag.list_sources()}


@app.post("/reload", dependencies=[Depends(require_api_key)])
def reload_index():
    """
    Reload the FAISS index from disk without restarting the service.

    Call this after an ingestion run has written a new index to the
    shared path this API reads from (`FAISS_INDEX_PATH`).
    """

    try:
        rag.reload_index()
    except Exception as exc:
        logger.error(f"Index reload failed: {exc}")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return {"status": "reloaded"}


@app.post("/reset-memory", dependencies=[Depends(require_api_key)])
def reset_memory(session_id: str = DEFAULT_SESSION_ID):
    rag.reset_memory(session_id)
    return {"status": "memory_reset", "session_id": session_id}
