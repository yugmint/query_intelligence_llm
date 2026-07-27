"""
Builds source citations from the chunks actually passed to generation.

Deliberately provenance, not verified per-claim attribution: this lists
what was provided as context (`RAGState["documents"]` after retrieval,
dedup, and reranking), not a guarantee the model actually drew on every
listed source in its final wording. The generation prompt
(src/prompts/generation.py) has no citation-marker instructions and the
existing structured-JSON-response path already isn't reliably honored
(see generate_knowledge.py) -- asking the model to self-report which
chunks it used would inherit that same unreliability. Chunk-provenance
citations are the honest, verifiable thing to offer instead.
"""

from langchain_core.documents import Document


def build_citations(documents: list[Document]) -> list[dict]:
    """
    One entry per distinct (source, page) pair, in the order each first
    appears in `documents` -- already relevance-ordered by the time this
    runs (retrieve -> dedup -> rerank), so the most relevant source
    citation comes first. `page` is None for sources without page-level
    metadata (ingestion_fixed's PDFLoader sets `page_number`; other
    loaders may not).
    """

    seen = set()
    citations = []

    for document in documents:
        source = document.metadata.get("source", "unknown")
        page = document.metadata.get("page_number")
        key = (source, page)

        if key in seen:
            continue

        seen.add(key)
        citations.append({"source": source, "page": page})

    return citations
