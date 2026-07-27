from dataclasses import dataclass
from typing import Any

from src.retrieval.bm25 import BM25Factory
from src.retrieval.embeddings import EmbeddingFactory
from src.retrieval.llm import LLMFactory
from src.retrieval.reranker import RerankerFactory
from src.retrieval.retriever import RetrieverFactory
from src.retrieval.vectorstore import VectorStoreFactory


@dataclass(slots=True)
class RAGResources:
    """
    Shared application resources.

    Deliberately does NOT hold conversation memory -- memory is
    per-session, not a process-wide singleton like the llm/embeddings/
    vectorstore/retriever/reranker are. Each request carries its own
    session's memory object through `RAGState["session_memory"]` instead
    (see RAGService.ask()). Mutating a resource here as a stand-in for
    "current session" would race under concurrent requests for
    different sessions.
    """

    llm: Any
    embeddings: Any
    vectorstore: Any
    retriever: Any
    reranker: Any
    # Sparse (BM25) half of hybrid search -- see src/retrieval/hybrid.py.
    # None whenever vectorstore/retriever are (no index yet), same
    # convention as them; defaults to None so existing call sites that
    # don't pass it (tests, mainly) don't have to change.
    bm25_retriever: Any = None


def build_resources() -> RAGResources:
    """
    Build all shared resources once.

    `vectorstore`/`retriever` may both be None if no FAISS index exists
    yet at startup (see VectorStoreFactory.load) -- deliberately not
    fatal, so the service can still start and serve /health while
    waiting for a first ingestion run. RAGService.ask() checks for this
    and returns a clear error rather than crashing on a None retriever.
    """

    # Build once
    embeddings = EmbeddingFactory.get()

    # Reuse the same embedding instance
    vectorstore = VectorStoreFactory.load(embeddings)

    retriever = RetrieverFactory.build(vectorstore) if vectorstore is not None else None

    bm25_retriever = BM25Factory.build(vectorstore) if vectorstore is not None else None

    reranker = RerankerFactory.get()

    llm = LLMFactory.get()

    return RAGResources(
        llm=llm,
        embeddings=embeddings,
        vectorstore=vectorstore,
        retriever=retriever,
        reranker=reranker,
        bm25_retriever=bm25_retriever,
    )