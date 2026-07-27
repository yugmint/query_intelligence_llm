# src/retrieval/bm25.py

from langchain_community.retrievers import BM25Retriever

from src.retrieval.config import RERANK_CANDIDATES


class BM25Factory:
    """
    Factory for a sparse (lexical) retriever, the other half of hybrid
    search (see src/retrieval/hybrid.py). Built directly from the
    vectorstore's own docstore -- FAISS's LangChain wrapper has no
    public "list all documents" API, so `vectorstore.docstore._dict`
    (private, but the only way in) is the same access pattern already
    used by RAGService.list_sources().

    Rebuilt (not incrementally updated) on every reload_index() call, in
    lockstep with the vectorstore -- BM25Retriever has no add-in-place
    API, and reloads are infrequent (only after an ingestion run), so
    rebuilding from scratch each time is simple and fast enough at the
    corpus sizes this project handles.
    """

    @staticmethod
    def build(vectorstore):
        documents = list(vectorstore.docstore._dict.values())

        if not documents:
            return None

        retriever = BM25Retriever.from_documents(documents)
        retriever.k = RERANK_CANDIDATES

        return retriever
