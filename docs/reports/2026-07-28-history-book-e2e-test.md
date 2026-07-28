# End-to-End Test Report — UPSC-Style Study-Guide Book

**Date:** 2026-07-28
**Document:** `ede93-history.pdf` (`ingestion_fixed/tests/local/data/books/`), a
Vision IAS "GS Mains 2025" History study-notes book — 117 pages, real UPSC
civil-services exam-prep content (Ancient/Medieval/Modern Indian history,
art & culture, post-Independence India). Requested as a representative
sample of this project's stated major target document type — the first one
tested this session.
**Pipeline versions:** `ingestion_fixed` v0.4.5, `RAG_Project_1` v0.5.8.
**Method:** every number below is real, captured output from the actual
pipeline/`RAGService`, not simulated. Isolated index at
`ingestion_fixed/local/test_reports/history_book_index/` (gitignored),
separate from every other test index.

---

## 1. Ingestion

Real end-to-end run, `IngestionPipeline.ingest()`:

- 117 pages → **688 chunks**, avg 520 chars/chunk, in 13.2s.
- Classified `general` (confidence 0.60), `recursive` strategy,
  chunk_size 500/overlap 100 — the "book" profile
  (chunk_size 800, `split_large_chunks=False`) was *not* picked, and on
  inspection that's the right call: this document is headings/bullets/
  tables-heavy exam-notes, not narrative prose the "book" profile assumes.
  Not a misclassification, just noting the recommendation held up.
- Layout correctly detected `has_headings=True`, `has_tables=True`,
  `has_lists=True` (confirmed by eye: nested `○` sub-bullets, a real
  Gandhara/Mathura/Amravati comparison table, all survived extraction
  intact in sampled chunks).
- `average_paragraph_length` came back sane (362 chars) — this document's
  blank-line paragraph breaks survived `pypdf` extraction fine, so the
  2026-07-28 fallback fix (v0.4.4) wasn't triggered here; a good negative
  control confirming that fix doesn't fire on documents that don't need it.

**Real, measurable issue found:** every page carries a repeating branding
header (`"AHMEDABAD | BENGALURU | ... | www.visionias.in # 8468022022
©Vision IAS"`). **115 of 688 chunks (16.7%) contain this noise verbatim.**
This is exactly `ingestion_fixed`'s still-open roadmap item ("TextCleaner
improvements: header/footer removal") — this document is real,
first-hand confirmation that it's not a hypothetical concern for the
project's actual target document type. Did not fix as part of this test
(out of scope for "run a test"); flagging as the most concrete evidence
yet for prioritizing that item.

**Also noted:** each chunk's `page_number` metadata reflects `pypdf`'s
structural page order (1-indexed from the start of the file), not this
document's own printed page-footer numbers (which start counting later,
after front matter — pypdf page 38 shows a footer reading "37"). Citations
returned by the API are therefore off by a small, page-dependent offset
from what a human would see printed on the page. Not a bug in this
project's code (there's no reliable way to parse a document's own printed
page numbers from `pypdf` text extraction), but worth knowing before
treating a citation's `page` as literally "the page number printed in the
book."

## 2. Retrieval + generation — grounded question set

Six questions, hand-picked from real content read directly out of the PDF
(not guessed), spanning the book's full range — ancient political history
to post-Independence foreign policy — plus one deliberately out-of-scope
question.

| # | Question | Answer | Correct? | Citations |
|---|---|---|---|---|
| 1 | Two types of Mahajanapada states? | Kingdoms (councils of ministers) + democratic ganas/sanghas | ✅ matches source (p.21) | p.21, p.22 |
| 2 | Schools of art tied to Mahayana Buddhism? | Gandhara and Mathura | ✅ exact match | p.41, p.33, p.26 |
| 3 | Bengali architecture, 1352–1576, key features? | Sloping curvilinear roofs, single-domed structures, terracotta ornamentation | ✅ exact match | p.61, p.58 |
| 4 | International events shaping 1920s–30s Indian revolutionaries? | Russian Revolution (1917), Irish nationalism, socialist ideas | ✅ exact match | p.81, p.85 |
| 5 | Outcome of the 1971 Indo-Pak War? | Decisive military victory for India, redrew South Asia's map | ✅ matches source | p.101, p.92 |
| 6 | *"What is quantum computing?"* (not in the book) | "I don't know." | ✅ correct refusal | p.23, p.43 (see §3) |

6/6 correct, including a clean refusal on the one genuinely out-of-scope
question — no hallucination, no confidently-wrong answers.

## 3. Feature-specific checks on this document

- **Citations:** correct and precise in every case above — spot-checked
  each against the actual source page's real text.
- **Citations on a refusal:** Q6 still returned 2 citations despite
  answering "I don't know." This is the documented, deliberate design
  (`src/services/citations.py`: chunk-provenance, not proof the model
  used them) — confirmed working as designed, not a bug, but a real
  example of the "I don't know" + citations combination a UI needs to
  handle sensibly.
- **Multi-turn / pronoun resolution:** "Tell me about the Imperial
  Cholas" → "What was **their** naval strength known for?" correctly
  resolved "their" to the Cholas (not a generic/wrong-topic answer) and
  answered correctly (control over Indian Ocean trade routes) with
  correct citations (p.61-62).
- **Metadata source filter:** re-asked a question with
  `metadata_filter={"source": "ede93-history.pdf"}` explicitly set —
  correct, grounded answer, unaffected (this index currently only has
  the one document, so this mainly confirms the filter path doesn't
  break on a single-document index, not that it excludes anything).
- **Hybrid search (BM25 + dense):** confirmed genuinely active — fusion
  changed the top-3 candidate ranking versus dense-only for a real query
  on this document.
- **Numeric-question widened path (`TOP_K_NUMERIC=8`):** "How many types
  of states did the Mahajanapadas have?" correctly triggered the widened
  path, used 8 chunks across 4 pages, answered correctly, **no 413** —
  confirms the `PARENT_CONTEXT_MAX_CHARS_PER_PAGE` fix (v0.5.8) holds on
  this document's real page sizes too, not just the one that originally
  triggered it.

## 4. Real finding: parent-child retrieval's benefit is muted on this
   document type

`average_page_length` for this book is **2,570 chars** — well above
`PARENT_CONTEXT_MAX_CHARS_PER_PAGE` (1,500, set in v0.5.8 specifically to
stop a real Groq 413). Checked directly: for a real query, all 3 matched
pages (2,988 / 3,595 / 2,367 chars) exceeded the cap, so every one of them
fell back to "matched chunk only" — parent expansion added **zero**
characters of context for this query. The safety fix holds (confirmed no
413, §3), but as currently tuned, parent-child retrieval provides close to
no benefit on this exact target document type, most of the time behaving
identically to pre-v0.5.8. Not fixed here — this is a real tuning
tradeoff (cap higher = richer parent context but reopens 413 risk,
especially combined with `TOP_K_NUMERIC=8`) that needs a decision, not a
quick edit.

## 5. Recommendation

Ship-quality on this document type: retrieval/generation accuracy is
solid (6/6 grounded + correct refusal), and the recent hardening
(hybrid search, parent-child, the 413 cap) all hold up on a real,
first-time-tested example of the project's actual target content. Two
concrete, evidence-backed follow-ups surfaced by this specific test:

1. **Header/footer removal** (already an open roadmap item) — now with
   a precise number behind it: 16.7% of chunks on this real document.
2. **`PARENT_CONTEXT_MAX_CHARS_PER_PAGE` re-tuning** (new finding) —
   current value neutralizes parent-child retrieval's benefit on
   book-length documents with this page density. Needs deciding: raise
   the cap and re-validate against the 413 risk, or accept the
   diminished benefit as the safe tradeoff.
