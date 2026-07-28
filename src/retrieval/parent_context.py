# src/retrieval/parent_context.py

"""
Parent-child retrieval: the small chunks reranking picked are what
matched the query precisely, but a small chunk alone can cut off
context the generator needs (a sentence started on the previous chunk,
a table row's header two chunks up).

v1 (2026-07-28) expanded to the chunk's *full page*. A real E2E test on
a real target-type book found that neutered the feature in practice:
book pages run denser than PARENT_CONTEXT_MAX_CHARS_PER_PAGE, so most
pages fell back to the matched chunk alone anyway (see
docs/05-roadmap.md v0.3.0 "Retrieval Context Strategy" follow-up).

v2 (this version) expands to the chunk's *neighbors by chunk_id*
instead -- `chunk_id` is a simple sequential index assigned once per
document at ingestion time (`MetadataGenerator`), so it's a reliable
reading-order key regardless of how much text a given page happens to
hold. Bounded by chunk *count* (PARENT_CONTEXT_NEIGHBOR_CHUNKS on each
side), not page size, so the context budget no longer depends on
document density -- the actual reason v1's cap kept firing.

Only expands `context` (what generation reads); `documents`/citations
stay scoped to the actual matched chunks -- a citation should point at
what was matched, not claim neighboring chunks were "the source".
"""

from langchain_core.documents import Document

from src.retrieval.config import PARENT_CONTEXT_NEIGHBOR_CHUNKS


def expand_to_parent_context(documents: list[Document], vectorstore) -> str:
    """
    Builds the generation context by expanding each matched chunk to
    itself plus its PARENT_CONTEXT_NEIGHBOR_CHUNKS nearest neighbors (by
    chunk_id, same source) on each side. Overlapping neighbor windows
    across different matched chunks are deduped -- each chunk_id
    contributes its text at most once. Chunks without a chunk_id
    (non-PDF loaders don't currently set one) or with no vectorstore
    fall back to their own text unchanged.
    """

    if vectorstore is None:
        return "\n\n".join(document.page_content for document in documents)

    # ponytail: O(corpus_size) scan to build the index, once per call --
    # fine at this project's corpus sizes (hundreds of chunks). Upgrade:
    # cache this on RAGResources, rebuilt in reload_index() alongside
    # bm25_retriever, if a much larger corpus makes this measurably slow.
    by_source: dict[str, dict[int, Document]] = {}
    for doc in vectorstore.docstore._dict.values():
        source = doc.metadata.get("source")
        chunk_id = doc.metadata.get("chunk_id")
        if source is None or chunk_id is None:
            continue
        by_source.setdefault(source, {})[chunk_id] = doc

    included: dict[str, set[int]] = {}
    fallback_parts = []

    for document in documents:
        source = document.metadata.get("source")
        chunk_id = document.metadata.get("chunk_id")

        if chunk_id is None or source not in by_source:
            fallback_parts.append(document.page_content)
            continue

        window = range(
            chunk_id - PARENT_CONTEXT_NEIGHBOR_CHUNKS,
            chunk_id + PARENT_CONTEXT_NEIGHBOR_CHUNKS + 1,
        )
        included.setdefault(source, set()).update(
            i for i in window if i in by_source[source]
        )

    parts = []
    for source, chunk_ids in included.items():
        chunk_map = by_source[source]
        ordered_ids = sorted(chunk_ids)

        # Group into contiguous runs so a real gap (two matched chunks
        # far apart in the same document) reads as a paragraph break,
        # not glued-together text that looks falsely continuous.
        run: list[int] = []
        for chunk_id in ordered_ids:
            if run and chunk_id != run[-1] + 1:
                parts.append("\n".join(chunk_map[i].page_content for i in run))
                run = []
            run.append(chunk_id)
        if run:
            parts.append("\n".join(chunk_map[i].page_content for i in run))

    parts.extend(fallback_parts)

    return "\n\n".join(parts)
