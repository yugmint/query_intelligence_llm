"""
Reciprocal Rank Fusion (RRF) -- merges FAISS's dense (embedding
similarity) candidate list with BM25's sparse (lexical) candidate list
into a single ranked list.

Why RRF specifically: BM25 scores and FAISS's cosine-similarity scores
live on incomparable scales, so averaging or otherwise combining the
raw scores directly would be meaningless. RRF sidesteps that entirely
by only using each list's *rank*, not its score -- a standard,
well-understood fusion technique for exactly this situation.
"""

from langchain_core.documents import Document

from src.retrieval.config import RRF_K


def reciprocal_rank_fusion(
    ranked_lists: list[list[Document]],
    k: int = RRF_K,
) -> list[Document]:
    """
    Merge several rank-ordered document lists into one, by summing
    1 / (k + rank) across every list a document appears in (rank is
    1-indexed) and sorting descending by that combined score.

    A document appearing near the top of *either* list scores well; one
    appearing near the top of *both* scores best of all. `page_content`
    is used as the identity key -- chunks are unique text spans in
    practice (confirmed empirically: no duplicate chunk content within a
    single real ingested index), and Document itself isn't hashable.

    `k` dampens the influence of exact rank position (a document at rank
    1 vs rank 2 matters less as k grows) -- 60 is the standard default
    from the original RRF paper, not tuned specifically for this project.
    """

    scores: dict[str, float] = {}
    doc_by_key: dict[str, Document] = {}

    for ranked in ranked_lists:
        for rank, document in enumerate(ranked, start=1):
            key = document.page_content
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank)
            doc_by_key.setdefault(key, document)

    ordered_keys = sorted(scores, key=lambda key: scores[key], reverse=True)

    return [doc_by_key[key] for key in ordered_keys]
