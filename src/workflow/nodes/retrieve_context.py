from src.retrieval.config import RERANK_CANDIDATES, RERANK_CANDIDATES_NUMERIC
from src.retrieval.hybrid import reciprocal_rank_fusion
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
    # applied when present. BM25 doesn't support per-document filtering
    # the same way, and the numeric-question fix already targets a
    # semantic-recall gap that lexical matching wouldn't help (the
    # distractor in that failure lexically matches the query *better*
    # than the correct chunk does) -- so hybrid search is deliberately
    # scoped to the plain, unfiltered, non-numeric path, the default and
    # far more common case.
    if metadata_filter or numeric:
        k = RERANK_CANDIDATES_NUMERIC if numeric else RERANK_CANDIDATES
        documents = resources.vectorstore.similarity_search(
            query, k=k, filter=metadata_filter
        )
    elif resources.bm25_retriever is not None:
        # Hybrid search: fuse FAISS's dense (embedding-similarity)
        # candidates with BM25's sparse (lexical) candidates via
        # Reciprocal Rank Fusion (src/retrieval/hybrid.py) -- catches
        # exact keyword/identifier matches (model names, acronyms, error
        # codes) that a bi-encoder embedding can under-rank, without
        # giving up the semantic matching dense search is good at.
        dense_documents = resources.retriever.invoke(query)
        bm25_documents = resources.bm25_retriever.invoke(query)
        documents = reciprocal_rank_fusion([dense_documents, bm25_documents])[
            :RERANK_CANDIDATES
        ]
    else:
        # No BM25 index available (e.g. resources built without one --
        # see BM25Factory) -- fall back to dense-only, unchanged from
        # before hybrid search existed.
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