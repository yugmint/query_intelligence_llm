import os
from collections import OrderedDict

from langchain_core.chat_history import InMemoryChatMessageHistory

from src.retrieval.bm25 import BM25Factory
from src.retrieval.memory import get_memory
from src.retrieval.retriever import RetrieverFactory
from src.retrieval.vectorstore import VectorStoreFactory
from src.services.citations import build_citations
from src.utils.chat_history import format_chat_history

from src.workflow.resources import build_resources
from src.workflow.workflow import build_workflow

from src.utils.logger import logger

DEFAULT_SESSION_ID = "default"

# Bounds the in-memory session store so public traffic with
# client-generated session_ids can't grow it indefinitely (a slow memory
# leak that's trivial to trigger -- send N distinct session_ids). LRU
# eviction: the least-recently-used session is dropped once the store is
# full, not the oldest-created one, so an active conversation is never
# evicted out from under it as long as it's still being used. 1000 is a
# generous default for a single small-instance deployment; override via
# env var if that's ever wrong for the actual traffic shape. See
# docs/05-roadmap.md and
# docs/reports/2026-07-26-performance-and-deployment-readiness.md.
MAX_SESSIONS = int(os.getenv("RAG_MAX_SESSIONS", "1000"))


class RAGService:
    """
    Public interface for interacting with the RAG system.

    Conversation memory is scoped per `session_id` -- each session gets
    its own InMemoryChatMessageHistory, created on first use. Callers that
    don't care about multi-session isolation (the CLI in main.py) can omit
    session_id entirely and get one implicit shared session, same as
    before.

    Note: this in-memory session store is per-process and non-persistent
    (lost on restart) -- fine for dev/demo/moderate traffic, not yet a
    real answer for long-running multi-instance production use (would
    need a shared backend, e.g. Redis, to survive restarts or work across
    multiple instances). It is, however, bounded (see `MAX_SESSIONS`) --
    unlike an unbounded dict, it can't grow without limit under public
    traffic. See docs/05-roadmap.md.
    """

    def __init__(self):

        logger.info("=" * 100)
        logger.info("Initializing RAG Service...")

        # session_id -> InMemoryChatMessageHistory, created lazily,
        # bounded + LRU-evicted -- see MAX_SESSIONS above.
        self._sessions: "OrderedDict[str, InMemoryChatMessageHistory]" = OrderedDict()

        # Initialize shared resources (llm/embeddings/vectorstore/retriever --
        # NOT memory, which is per-session, see workflow/resources.py)
        self.resources = build_resources()

        # Build LangGraph workflow
        self.workflow = build_workflow(self.resources)

        logger.info("RAG Service initialized successfully.")
        logger.info("=" * 100)

    def _set_session(self, session_id: str, memory: InMemoryChatMessageHistory) -> None:
        """
        Insert/replace a session's memory, evicting the least-recently-used
        entry first if the store is already at `MAX_SESSIONS`. Shared by
        both session creation and `reset_memory` so neither path can
        bypass the bound.
        """

        if session_id not in self._sessions and len(self._sessions) >= MAX_SESSIONS:
            evicted_id, _ = self._sessions.popitem(last=False)
            logger.info(
                f"Session store at capacity ({MAX_SESSIONS}); "
                f"evicted least-recently-used session '{evicted_id}'."
            )

        self._sessions[session_id] = memory
        self._sessions.move_to_end(session_id)

    def _get_session_memory(self, session_id: str) -> InMemoryChatMessageHistory:
        if session_id in self._sessions:
            self._sessions.move_to_end(session_id)
            return self._sessions[session_id]

        logger.debug(f"Creating new conversation memory for session '{session_id}'.")
        memory = get_memory()
        self._set_session(session_id, memory)

        return memory

    def ask(
        self,
        query: str,
        session_id: str = DEFAULT_SESSION_ID,
        return_state: bool = False,
        metadata_filter: dict | None = None,
    ):
        """
        Ask a question to the RAG system.

        Parameters
        ----------
        query : str
            User query.

        session_id : str
            Which conversation this query belongs to. Queries with
            different session_ids never see each other's history.

        return_state : bool
            If True, returns the complete workflow state.
            Otherwise returns only the generated answer.

        metadata_filter : dict | None
            Optional filter applied at retrieval time, e.g.
            {"source": "EfficientNet.pdf"} to scope this query to one
            previously-ingested document instead of searching the whole
            index. None (default) searches everything, unchanged from
            before this existed. See RAGState.metadata_filter and
            nodes/retrieve_context.py for how it's applied.

        Returns
        -------
        str | dict
        """

        logger.info("")
        logger.info("=" * 100)
        logger.info(f"New Query [session={session_id}] : {query}")

        if self.resources.retriever is None:
            # No FAISS index loaded yet (fresh shared volume, ingestion
            # hasn't run yet) -- see VectorStoreFactory.load. Answer
            # clearly instead of crashing inside the retrieve node, and
            # keep the service itself up (so /health still reports OK and
            # container orchestration doesn't restart-loop it) while
            # waiting for a first ingestion run + reload_index() call.
            # See docs/05-roadmap.md.
            logger.warning("No FAISS index loaded -- refusing to answer.")
            answer = (
                "I don't have any documents loaded yet, so I can't answer "
                "questions right now. Please try again shortly."
            )
            if return_state:
                return {
                    "query": query,
                    "answer": answer,
                    "intent": "",
                    "status": "no_index",
                    "session_id": session_id,
                    "citations": [],
                }
            return answer

        memory = self._get_session_memory(session_id)
        chat_history = format_chat_history(memory.messages)

        initial_state = {

            "query": query,

            "intent": "",

            "rewritten_query": "",

            "metadata_filter": metadata_filter,

            "documents": [],

            "context": "",

            "chat_history": chat_history,

            "session_id": session_id,

            "session_memory": memory,

            "answer": "",

            "retry_count": 0,

            "metadata": {},
        }

        result = self.workflow.invoke(initial_state)

        logger.info("Workflow execution completed.")

        # Provenance for whatever chunks were actually handed to
        # generation -- see src/services/citations.py for why this is
        # chunk-provenance, not verified per-claim attribution. Computed
        # here rather than as a graph node: it's a response-shaping
        # concern over the final state, not something any node reads or
        # writes mid-workflow.
        result["citations"] = build_citations(result.get("documents", []))

        if return_state:
            return result

        return result["answer"]

    def reset_memory(self, session_id: str = DEFAULT_SESSION_ID):
        """
        Clears conversation history for one session (default: the
        implicit shared session used when no session_id is passed).
        """

        logger.info(f"Resetting conversation memory for session '{session_id}'.")

        self._set_session(session_id, get_memory())

        logger.info("Conversation memory cleared.")

    def reload_index(self):
        """
        Reload the FAISS vectorstore from disk in place.

        The compiled LangGraph workflow closes over `self.resources` by
        reference, not by value, so mutating its `vectorstore` / `retriever`
        fields here is picked up immediately by every node -- no need to
        rebuild the graph. This is what lets a separate ingestion service
        (writing to the same shared index path) hand off a freshly built
        index without restarting this process.
        """

        logger.info("Reloading vector index from disk...")

        vectorstore = VectorStoreFactory.load(self.resources.embeddings)
        self.resources.vectorstore = vectorstore
        self.resources.retriever = (
            RetrieverFactory.build(vectorstore) if vectorstore is not None else None
        )
        # BM25Retriever has no add-in-place API -- rebuilt from scratch
        # in lockstep with the vectorstore, same as retriever above.
        self.resources.bm25_retriever = (
            BM25Factory.build(vectorstore) if vectorstore is not None else None
        )

        if vectorstore is None:
            logger.warning(
                "reload_index(): still no FAISS index found -- staying "
                "in 'no index loaded' mode."
            )
        else:
            logger.info("Vector index reloaded.")

    def list_sources(self) -> list[dict]:
        """
        Distinct documents currently in the index, with a chunk count
        and (best-effort) document_type per source -- lets a caller
        discover valid values for ask()'s metadata_filter/the API's
        `source` field before guessing at a filename. Without this,
        source-filtering is nearly unusable in practice: there was no
        way to know what's actually in the index to filter by.

        FAISS's LangChain wrapper has no public "list all documents"
        API; `vectorstore.docstore._dict` (private, but the only way in)
        is the same access pattern already used throughout this
        project's own debugging/validation scripts this session.
        """

        if self.resources.vectorstore is None:
            return []

        counts: dict[str, dict] = {}
        for doc in self.resources.vectorstore.docstore._dict.values():
            source = doc.metadata.get("source", "unknown")
            entry = counts.setdefault(
                source,
                {"source": source, "document_type": doc.metadata.get("document_type"), "chunk_count": 0},
            )
            entry["chunk_count"] += 1

        return sorted(counts.values(), key=lambda e: e["source"])
