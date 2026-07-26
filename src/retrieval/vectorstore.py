# src/retrieval/vectorstore.py

from pathlib import Path
from typing import Optional

from langchain_community.vectorstores import FAISS
from src.retrieval.embeddings import EmbeddingFactory

from src.retrieval.config import FAISS_PATH
from src.utils.logger import logger


class VectorStoreFactory:
    """Factory for FAISS vector store."""

    @staticmethod
    def load(embeddings=None) -> Optional[FAISS]:
        """
        Returns None (rather than raising) if no index exists yet at
        FAISS_PATH -- on a brand-new shared volume, this service starts
        before the sibling ingestion service has written a first index.
        Checking for the index file explicitly (rather than catching
        FAISS.load_local's RuntimeError and inspecting its message) keeps
        this from also silently swallowing a *different* failure, like a
        corrupted or permission-denied index. Callers (RAGService,
        reload_index) must handle a None return -- see
        docs/05-roadmap.md and the shared docker-compose.yml's comments.
        """

        embeddings = embeddings or EmbeddingFactory.get()

        index_file = Path(FAISS_PATH) / "index.faiss"
        if not index_file.exists():
            logger.warning(
                f"No FAISS index found at '{FAISS_PATH}' (expected "
                f"{index_file}) -- starting without one. /query will "
                f"return a clear error until an ingestion run has "
                f"written an index and reload_index() has been called."
            )
            return None

        return FAISS.load_local(
            FAISS_PATH,
            embeddings,
            allow_dangerous_deserialization=True,
        )


def load_vectorstore(embeddings=None):
    return VectorStoreFactory.load(embeddings)
