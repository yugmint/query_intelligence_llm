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

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel

from src.services.rag_service import DEFAULT_SESSION_ID, RAGService
from src.utils.auth import require_api_key
from src.utils.logger import logger

app = FastAPI(title="RAG Query API", version="0.1.0")

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
def query(request: QueryRequest):
    if not request.query or not request.query.strip():
        raise HTTPException(status_code=400, detail="query must not be empty")

    try:
        state = rag.ask(request.query, session_id=request.session_id, return_state=True)
    except Exception as exc:
        # The LLM call inside this workflow already retries transient
        # failures (LLMFactory's max_retries + client-side rate limiting --
        # see src/retrieval/llm.py); anything that still reaches here is
        # either a genuinely exhausted retry budget or an unrelated bug.
        # Either way, callers should see a clean 503, not an unhandled
        # exception's stack trace. Confirmed necessary by an actual crash
        # under concurrent load -- see
        # docs/reports/2026-07-26-performance-and-deployment-readiness.md.
        logger.error(f"Query failed for session '{request.session_id}': {exc}")
        raise HTTPException(
            status_code=503,
            detail="The assistant is temporarily unavailable. Please try again shortly.",
        ) from exc

    return QueryResponse(
        answer=state.get("answer", ""),
        intent=state.get("intent", ""),
        status=state.get("status", ""),
        session_id=request.session_id,
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
