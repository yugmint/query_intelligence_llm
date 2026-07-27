from src.retrieval.config import RERANK_CANDIDATES, RERANK_CANDIDATES_NUMERIC
from src.processing.numeric_question import is_numeric_question
from src.workflow.state import RAGState
from src.workflow.resources import RAGResources

from src.utils.decorators import log_node
from src.utils.logger import logger


@log_node("Retrieve_Context")
def retrieve_documents(
    state: RAGState,
    resources: RAGResources,
):

    # ------------------------
    # Prepare
    # ------------------------

    query = state.get("rewritten_query") or state["query"]
    metadata_filter = state.get("metadata_filter")
    numeric = is_numeric_question(query)

    logger.info(
        f"Retrieval Query : {query}"
        )
    if metadata_filter:
        logger.info(f"Metadata Filter : {metadata_filter}")
    if numeric:
        logger.info("Numeric question detected -- widening candidate pool.")

    # ------------------------
    # Execute
    # ------------------------

    # resources.retriever is a VectorStoreRetriever built once at startup
    # with a fixed search_kwargs (see RetrieverFactory) -- it has no way
    # to accept a per-query filter or a per-query k. Go straight to the
    # vectorstore instead whenever either is needed (a metadata filter,
    # or a numeric question that needs a wider-than-default candidate
    # pool -- see RERANK_CANDIDATES_NUMERIC in src/retrieval/config.py);
    # same underlying FAISS index, just with FAISS's own filter support
    # (dict of metadata key->value, or its $and/$or/$in/etc operators)
    # applied when present. Falls back to the existing retriever for the
    # plain, unfiltered, non-numeric (default, far more common) case,
    # leaving that path's behavior untouched.
    if metadata_filter or numeric:
        k = RERANK_CANDIDATES_NUMERIC if numeric else RERANK_CANDIDATES
        documents = resources.vectorstore.similarity_search(
            query, k=k, filter=metadata_filter
        )
    else:
        documents = resources.retriever.invoke(query)

    context = "\n\n".join(
        document.page_content
        for document in documents
    )

    # ------------------------
    # Business Metrics
    # ------------------------

    logger.info(f"Retrieved Documents : {len(documents)}")
    logger.info(f"Context Length      : {len(context)} chars")

    # Optional (avoid logging huge content)
    logger.debug(f"Context Preview:\n{context[:300]}")

    # ------------------------
    # Return
    # ------------------------

    return {
        "documents": documents,
        "context": context,
        "is_numeric_question": numeric,
    }