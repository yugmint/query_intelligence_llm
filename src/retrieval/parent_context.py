# src/retrieval/parent_context.py

"""
Parent-child retrieval: the small chunks reranking picked are what
matched the query precisely, but a small chunk alone can cut off
context the generator needs (a sentence started on the previous chunk,
a table row's header two chunks up). The "parent" here is simply the
full page the chunk came from -- ingestion already tags every PDF
chunk with page_number/source (src/utils/metadata in ingestion_fixed),
so no separate parent-document store is needed; the vectorstore
already holds every chunk from that page.

Only expands `context` (what generation reads); `documents`/citations
stay scoped to the actual matched chunks -- a citation should point at
what was matched, not claim the whole page was "the source".
"""

from langchain_core.documents import Document

from src.retrieval.config import PARENT_CONTEXT_MAX_CHARS_PER_PAGE


def expand_to_parent_context(documents: list[Document], vectorstore) -> str:
    """
    Builds the generation context by expanding each document to its
    full parent page's text (same source + page_number), deduped so two
    selected chunks from the same page don't repeat that page twice.
    Falls back to the chunk's own text when there's no page_number
    (non-paginated formats: .txt/.html/.docx), no vectorstore, or the
    page is too large to expand safely (see below).
    """

    if vectorstore is None:
        return "\n\n".join(document.page_content for document in documents)

    # ponytail: O(top_k * corpus_size) scan, fine at this project's
    # corpus sizes (hundreds of chunks). Upgrade: a (source, page) ->
    # chunks index built once in BM25Factory-style resource setup if a
    # much larger corpus ever makes this measurably slow.
    all_documents = list(vectorstore.docstore._dict.values())

    parts = []
    seen_pages = set()

    for document in documents:
        source = document.metadata.get("source")
        page = document.metadata.get("page_number")

        if page is None:
            parts.append(document.page_content)
            continue

        key = (source, page)
        if key in seen_pages:
            continue
        seen_pages.add(key)

        page_chunks = [
            d.page_content
            for d in all_documents
            if d.metadata.get("source") == source and d.metadata.get("page_number") == page
        ]
        full_page = "\n".join(page_chunks) if page_chunks else document.page_content

        # A page over budget can't be truncated blindly -- the matched
        # chunk (the actual reason this page was pulled in) could sit
        # anywhere in it, and slicing from the start risks cutting the
        # relevant part out of its own expanded context. Fall back to
        # just the matched chunk instead of a possibly-broken slice; a
        # real 413 from Groq (TOP_K_NUMERIC=8 chunks each expanding to a
        # full dense page) confirmed this budget matters in practice.
        if len(full_page) > PARENT_CONTEXT_MAX_CHARS_PER_PAGE:
            parts.append(document.page_content)
        else:
            parts.append(full_page)

    return "\n\n".join(parts)
