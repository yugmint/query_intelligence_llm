from src.retrieval.config import RERANK_CANDIDATES, RERANK_CANDIDATES_NUMERIC
from src.retrieval.hybrid import reciprocal_rank_fusion
from src.processing.comparison_question import extract_comparison_sides, is_implicit_comparison
from src.processing.numeric_question import is_numeric_question
from src.workflow.state import RAGState
from src.workflow.resources import RAGResources

from src.utils.decorators import log_node
from src.utils.logger import logger


def _dedupe_documents(documents):
    seen = set()
    deduped = []
    for document in documents:
        key = (document.metadata.get("source"), document.metadata.get("chunk_id"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(document)
    return deduped


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

    # Comparison questions come in two real shapes (see
    # src/processing/comparison_question.py) -- explicit ("Compare X
    # and Y") names both sides, implicit ("Which X had the better Y?")
    # doesn't. Mutually exclusive: only check for the implicit shape
    # once the explicit one has failed to match.
    comparison_sides = extract_comparison_sides(query)
    implicit_comparison = comparison_sides is None and is_implicit_comparison(query)
    is_comparison = comparison_sides is not None or implicit_comparison

    logger.info(
        f"Retrieval Query : {query}"
        )
    if metadata_filter:
        logger.info(f"Metadata Filter : {metadata_filter}")
    if numeric:
        logger.info("Numeric question detected -- widening candidate pool.")
    if comparison_sides is not None:
        logger.info(f"Comparison question detected -- sides: {comparison_sides}")
    elif implicit_comparison:
        logger.info("Implicit comparison question detected -- widening candidate pool.")

    # ------------------------
    # Execute
    # ------------------------

    if comparison_sides is not None:
        # Both sides named -- retrieve each independently and merge, so
        # one side can't crowd the other out of a single ranked list
        # the way one combined query would (confirmed as the real
        # shape of this project's own "Compare X and Y" benchmark
        # cases -- see docs/05-roadmap.md v0.6.0). Deliberately
        # dense-only per side (skips BM25/hybrid fusion) -- no evidence
        # yet that lexical matching is needed on top of this, and two
        # dense searches is already double the retrieval work a normal
        # query does.
        side_a, side_b = comparison_sides
        documents = _dedupe_documents(
            resources.vectorstore.similarity_search(side_a, k=RERANK_CANDIDATES, filter=metadata_filter)
            + resources.vectorstore.similarity_search(side_b, k=RERANK_CANDIDATES, filter=metadata_filter)
        )
    elif metadata_filter or numeric or implicit_comparison:
        # resources.retriever is a VectorStoreRetriever built once at startup
        # with a fixed search_kwargs (see RetrieverFactory) -- it has no way
        # to accept a per-query filter or a per-query k. Go straight to the
        # vectorstore instead whenever any of these is needed: a metadata
        # filter, a numeric question, or an implicit comparison, all of
        # which need a wider-than-default candidate pool (see
        # RERANK_CANDIDATES_NUMERIC in src/retrieval/config.py -- reused
        # here rather than a new comparison-specific constant, since the
        # underlying reason is the same: TOP_K=3 is too narrow for either
        # task). BM25 doesn't support per-document filtering the same way,
        # and the numeric-question fix already targets a semantic-recall
        # gap that lexical matching wouldn't help (the distractor in that
        # failure lexically matches the query *better* than the correct
        # chunk does) -- so hybrid search is deliberately scoped to the
        # plain, unfiltered, non-numeric, non-comparison path, the
        # default and far more common case.
        k = RERANK_CANDIDATES_NUMERIC if (numeric or implicit_comparison) else RERANK_CANDIDATES
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
        "is_comparison_question": is_comparison,
    }
