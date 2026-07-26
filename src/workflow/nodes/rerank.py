from src.retrieval.config import TOP_K
from src.workflow.resources import RAGResources
from src.workflow.state import RAGState

from src.utils.decorators import log_node
from src.utils.logger import logger


@log_node("Rerank")
def rerank_documents(
    state: RAGState,
    resources: RAGResources,
):
    """
    Narrows the wider FAISS candidate pool (RERANK_CANDIDATES, from
    nodes/retrieve_context.py) down to TOP_K using a cross-encoder, which
    scores (query, chunk) pairs jointly -- much more precise than the
    bi-encoder similarity search FAISS already did to produce the
    candidate pool in the first place. This is what plain top-k similarity
    search alone couldn't do: recover a genuinely relevant chunk that
    ranked outside the old un-reranked top-3 (confirmed happening in
    practice -- see docs/reports/2026-07-24-*.md).

    Rebuilds `context` from the reranked, trimmed set -- the wider
    candidate pool's un-reranked context (built in retrieve_context.py)
    is not what should reach the generation prompt.
    """

    # ------------------------
    # Prepare
    # ------------------------

    query = state.get("rewritten_query") or state["query"]
    candidates = state.get("documents", [])

    # Reference-list chunks (bibliography entries) are essentially never
    # a useful answer on their own, and their citation-style formatting
    # ("Authors. Title. Venue, Year.") has been mistaken by generation
    # for the document's own title -- see docs/05-roadmap.md. Drop them
    # from the candidate pool before scoring, with a fallback: if every
    # candidate happens to be reference-section content (e.g. a query
    # genuinely about citations), don't filter down to nothing.
    non_reference_candidates = [
        document
        for document in candidates
        if not document.metadata.get("is_reference_section")
    ]
    if non_reference_candidates:
        candidates = non_reference_candidates

    if not candidates:
        logger.info("No candidates to rerank.")
        return {"documents": [], "context": ""}

    # ------------------------
    # Execute
    # ------------------------

    pairs = [(query, document.page_content) for document in candidates]
    scores = resources.reranker.predict(pairs)

    ranked = sorted(
        zip(scores, candidates),
        key=lambda pair: pair[0],
        reverse=True,
    )

    top_documents = [document for _score, document in ranked[:TOP_K]]

    context = "\n\n".join(
        document.page_content
        for document in top_documents
    )

    # ------------------------
    # Business Metrics
    # ------------------------

    logger.info(f"Reranked {len(candidates)} candidates -> kept top {len(top_documents)}")
    logger.info(f"Top scores: {[round(float(s), 3) for s, _ in ranked[:TOP_K]]}")
    logger.info(f"Context Length : {len(context)} chars")

    # ------------------------
    # Return
    # ------------------------

    return {
        "documents": top_documents,
        "context": context,
    }
