from difflib import SequenceMatcher

from src.retrieval.config import CHUNK_DEDUP_SIMILARITY_THRESHOLD, TOP_K, TOP_K_NUMERIC
from src.retrieval.parent_context import expand_to_parent_context
from src.workflow.resources import RAGResources
from src.workflow.state import RAGState

from src.utils.decorators import log_node
from src.utils.logger import logger


def _select_diverse_top_k(ranked, top_k: int):
    """
    Greedily walk `ranked` (score-descending (score, Document) pairs) and
    keep the highest-scoring chunks, skipping any candidate that's a
    near-duplicate (see CHUNK_DEDUP_SIMILARITY_THRESHOLD) of one already
    selected. Lets a genuinely distinct, lower-scoring chunk fill the
    slot a near-duplicate would otherwise have crowded out of TOP_K --
    the cross-encoder scores each candidate independently and has no
    notion of redundancy against what it's already picked.

    Can return fewer than `top_k` documents if there aren't enough
    distinct candidates -- matches the existing "fewer candidates than
    TOP_K keeps all of them" behavior rather than padding with
    duplicates.

    Returns the selected (score, Document) pairs, same shape as `ranked`,
    so callers can still log/use the scores of what was actually kept.
    """

    selected: list = []
    skipped = 0

    for score, document in ranked:
        if len(selected) >= top_k:
            break

        is_duplicate = any(
            SequenceMatcher(
                None, document.page_content, kept.page_content
            ).ratio()
            >= CHUNK_DEDUP_SIMILARITY_THRESHOLD
            for _kept_score, kept in selected
        )

        if is_duplicate:
            skipped += 1
            continue

        selected.append((score, document))

    if skipped:
        logger.info(f"Skipped {skipped} near-duplicate candidate(s).")

    return selected


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

    # Numeric questions get a wider TOP_K -- the whole reason
    # retrieve_context.py widened the candidate pool for them in the
    # first place is that the correct chunk can rank well outside the
    # default TOP_K=3 even after reranking. See RERANK_CANDIDATES_NUMERIC/
    # TOP_K_NUMERIC in src/retrieval/config.py.
    top_k = TOP_K_NUMERIC if state.get("is_numeric_question") else TOP_K
    selected = _select_diverse_top_k(ranked, top_k)
    top_documents = [document for _score, document in selected]

    # Parent-child retrieval: generation reads each chunk plus its
    # chunk_id neighbors instead of just the matched chunk alone -- see
    # src/retrieval/parent_context.py. documents/citations below still
    # reflect the actual matched (small) chunks, unchanged.
    context = expand_to_parent_context(top_documents, resources.vectorstore)

    # ------------------------
    # Business Metrics
    # ------------------------

    logger.info(f"Reranked {len(candidates)} candidates -> kept top {len(top_documents)}")
    logger.info(f"Top scores: {[round(float(s), 3) for s, _ in selected]}")
    logger.info(f"Context Length : {len(context)} chars")

    # ------------------------
    # Return
    # ------------------------

    return {
        "documents": top_documents,
        "context": context,
    }
