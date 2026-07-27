# src/workflow/state.py

from typing import Any, TypedDict

from langchain_core.documents import Document


class RAGState(TypedDict):
    """
    Shared state passed between LangGraph nodes.
    """

    # -------------------------
    # User Input
    # -------------------------
    query: str
    rewritten_query: str
    # Optional metadata filter applied at retrieval time, e.g.
    # {"source": "EfficientNet.pdf"} to scope a query to one previously
    # -ingested document. None means unfiltered (search everything in
    # the index), the existing/default behavior. Passed straight through
    # to FAISS's own filter support (dict of metadata key -> value, or
    # MongoDB-style operators -- see FAISS._create_filter_func) by
    # nodes/retrieve_context.py. Matters now that ingestion is additive
    # (v0.4.0) -- one index can hold multiple unrelated documents, and
    # without this a query has no way to avoid searching all of them.
    metadata_filter: dict[str, Any] | None

    # -------------------------
    # Guardrails
    # -------------------------
    is_valid: bool
    guardrail_reason: str | None

    # -------------------------
    # Intent
    # -------------------------
    intent: str

    # -------------------------
    # Retrieval
    # -------------------------
    # Matches what nodes/retrieve_context.py actually writes. Was
    # declared as retrieved_documents/reranked_documents until 2026-07-24
    # -- neither was ever written by any node, so the declared contract
    # didn't match reality. reranked_documents will come back once
    # reranking (roadmap v0.2.0) actually exists; no point declaring it
    # speculatively before then.
    documents: list[Document]
    context: str

    # -------------------------
    # Conversation
    # -------------------------
    chat_history: str
    session_id: str
    # The current session's InMemoryChatMessageHistory instance, carried
    # through state (not resources) so concurrent requests for different
    # sessions never share or race on the same memory object. Populated
    # by RAGService.ask(), consumed/written by nodes/update_memory.py.
    session_memory: Any

    # -------------------------
    # Generation
    # -------------------------
    answer: str

    # -------------------------
    # Workflow
    # -------------------------
    retry_count: int
    status: str

    # -------------------------
    # Observability
    # -------------------------
    metadata: dict[str, Any]