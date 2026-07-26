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

import os

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from src.services.rag_service import DEFAULT_SESSION_ID, RAGService
from src.utils.auth import require_api_key
from src.utils.logger import logger

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


class QueryResponse(BaseModel):
    answer: str
    intent: str = ""
    status: str = ""
    session_id: str = DEFAULT_SESSION_ID


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/query", response_model=QueryResponse, dependencies=[Depends(require_api_key)])
@limiter.limit("10/minute")
def query(request: Request, body: QueryRequest):
    if not body.query or not body.query.strip():
        raise HTTPException(status_code=400, detail="query must not be empty")

    try:
        state = rag.ask(body.query, session_id=body.session_id, return_state=True)
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
        raise HTTPException(
            status_code=503,
            detail="The assistant is temporarily unavailable. Please try again shortly.",
        ) from exc

    return QueryResponse(
        answer=state.get("answer", ""),
        intent=state.get("intent", ""),
        status=state.get("status", ""),
        session_id=body.session_id,
    )


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
