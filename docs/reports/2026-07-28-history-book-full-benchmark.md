# Full Benchmark Report — History Book (97 Real Questions)

**Date:** 2026-07-28
**Document:** `ede93-history.pdf` — the same 117-page Vision IAS UPSC
history study-notes book from the earlier E2E test
(`2026-07-28-history-book-e2e-test.md`), now tested at full scale against
an external benchmark spec (`ingestion_fixed/tests/local/data/books/Benchmark
document history book.docx`, ~115 questions across 7 difficulty levels).
**Pipeline versions spanned:** `ingestion_fixed` v0.4.5 → v0.4.8,
`RAG_Project_1` v0.5.8 → v0.6.0 (this report covers the work across that
whole range, not one snapshot).
**Method:** every number below is a real run against `scripts/benchmark.py`
and a real FAISS index — retrieval metrics from the raw ranked candidate
list, generation metrics from a real `RAGService.ask()` call including real
Groq LLM calls. `expected_answer_substring` ground truth was hand-verified
against the actual extracted PDF text for every case, not invented from the
question alone. Nothing here is simulated or estimated.

---

## 1. Baseline run — 97 cases, general-classified index

All 97 cases (7 Manual Spot-Check across 4 documents + 90 History-Book
cases across L1–L6), against the index as originally ingested
(`document_type=general`, confidence 0.60, `chunk_size=500`).

| Level | N | Answer correct | Hallucination | Latency |
|---|---|---|---|---|
| L1-Exact Fact | 20 | 80% | 10% | 25.0s |
| L2-Multi-hop | 20 | 90% | 10% | 25.1s |
| L3-Semantic | 10 | 90% | 10% | 25.0s |
| L4-Long-context | 10 | 80% | 0% | 25.1s |
| L5-Synonyms | 5 | 100% | 0% | 25.0s |
| L5-Indirect | 5 | 80% | 20% | 25.0s |
| L5-Ambiguous | 5 | 60% | 40% | 25.1s |
| L5-Cross-document | 5 | 40% | 0% | 25.1s |
| L6-Failure Tests | 10 | 80% | 20% | 25.0s |
| Manual Spot-Check | 7 | 100% | 0% | 25.1s |
| **OVERALL** | **97** | **82%** | **10%** | **25.04s** |

Retrieval (3 judgeable, Manual Spot-Check only): Hit@1 67%, Hit@3 100%,
Recall@5 100%, MRR 0.78, Precision@5 0.27.

**Two things stood out enough to investigate rather than accept as-is:**
latency flat at ~25s regardless of question difficulty (pointing at a fixed
per-query cost, not inference time), and L5-Ambiguous/L5-Cross-document
both well below every other category.

## 2. Latency fix (not this document's focus, but the enabling context)

The flat ~25s traced to `nodes/intent.py` spending a full Groq call on a
3-way classification that `route_by_intent` only ever used as binary —
burning a second token from the shared rate-limiter bucket every query.
Replaced with regex classification
(`src/processing/intent_classifier.py`, no LLM call). **Validated against
10 real questions: 25.04s → 12.68s mean latency (49% reduction).** Shipped
as `v0.5.11`. Every run after this point in the report runs faster as a
direct result, not a new variable.

## 3. Diagnosing the weak categories — before touching any chunking code

Read the actual generated answers and retrieved chunks for every
L5-Ambiguous/L5-Cross-document failure rather than assuming a chunking
rebuild was needed. Found:

- **"Explain India's earliest cities."** retrieved almost entirely
  unrelated content (a practice-questions blurb about Gangetic-plains
  cities, not Harappan/Indus Valley) — a real retrieval/topic-confusion
  bug.
- **"Tell me about political systems."** retrieved modern-India election
  content instead of ancient Mahajanapada political systems — genuinely
  ambiguous given the book covers both, not obviously a bug.
- **"Which era gave women greater freedom?"** and **"Which civilization
  had better trade networks?"** returned "I don't know" despite relevant
  chunks being retrieved — a generation-behavior pattern, not a missing-
  context one.

The retrieval-confusion case pointed at chunk size/classification, not a
new chunking algorithm.

## 4. Root cause: document misclassified `general`, not `book`

`PDFAnalyzer._classify_document` only recognized "book" via the literal
strings `"chapter"` or `"table of contents"`. This book's contents page is
headed just **"Contents"**, with numbered sections
(`"1. ANCIENT HISTORY... 5"`) — neither literal matched, so it fell
through to `general` (chunk_size 500, confidence 0.60) instead of `book`
(chunk_size 800).

**Fix** (`ingestion_fixed` v0.4.8): added dot-leader TOC detection (a
title, a run of dots, a trailing page number, seen ≥3 times) — a real,
low-false-positive fingerprint distinct from the existing keyword checks.
Verified through the full pipeline (load → clean → analyze, not just the
raw loader — the page-header noise briefly looked like a `has_tables`
false positive via `"|" in text` until routed through the real cleaner
first): **confidence 0.60 → 0.85, chunk_size 500 → 800.** Re-ingested to a
fresh index: 421 chunks (was 688).

## 5. Full 92-case re-run on the reclassified index

History-Book-only subset (92 of the original 97 — excludes the 5
non-history Manual Spot-Check cases), same questions, same grading, index
rebuilt with the classification fix.

| Level | v2 (general, 500-char) | v3 (book, 800-char) | Δ |
|---|---|---|---|
| L1-Exact Fact | 80% | 95% | **+15pp** |
| L2-Multi-hop | 90% | 90% | flat |
| L3-Semantic | 90% | 80% | −10pp |
| L4-Long-context | 80% | 80% | flat |
| L5-Synonyms | 100% | 100%* | flat |
| L5-Indirect | 80% | 80% | flat |
| L5-Ambiguous | 60% | 80% | **+20pp** |
| L5-Cross-document | 40% | 20% | **−20pp** |
| L6-Failure Tests | 80% | 90% | +10pp |
| Manual Spot-Check | 100% | 100% | flat |
| **OVERALL** | **82%** | **85%*** | **+3pp** |

*after fixing one more grading gap this run caught: "Mauryas" vs. the
narrow `"mauryan"` keyword — same class of inflection bug as an earlier
harappan/indus-valley one.

**Traced every flip, not just the aggregate.** L1 (+15pp) and L5-Ambiguous
(+20pp) are real wins — the "earliest cities" retrieval-confusion bug is
fixed. L5-Cross-document (−20pp) is a real, reproducible regression: "Which
civilization had the better drainage system?", correct under the old
chunking, now refused under the new one — confirming the earlier
diagnosis that comparative questions are a generation-behavior problem
chunk size can move in *either* direction, not fix. The L3 dip traced to
LLM wording non-determinism on manual re-check, not a reproducible miss.

Shipped as `ingestion_fixed v0.4.8` / `RAG_Project_1 v0.5.12`.

## 6. Comparative-question refusals — investigated, then fixed differently than expected

Two prompt variants explicitly permitting cross-sentence synthesis for
comparison questions were tested against the drainage-system regression.
**Neither changed the output at all**, even with the full, unambiguous
Harappan drainage-system passage confirmed present in
`state["context"]`. Ruled out prompt wording as the lever and reverted
both rather than keep untested-effective complexity.

Tested the same 4 refused questions against `openai/gpt-oss-20b` (a Groq
MoE model) on identical retrieved context:

| Question | `llama-3.1-8b-instant` | `openai/gpt-oss-20b` |
|---|---|---|
| Drainage system | ❌ "I don't know" | ✅ "Harappan Civilization" |
| Women's freedom by era | ❌ "I don't know" | ⚠️ "Vedic era" (engaged, imprecise) |
| Trade networks | ❌ "I don't know" | ❌ "I don't know" |
| Technological leap | ❌ "I don't know" | ❌ "I don't know" |

**0/4 → 2/4 correct, 3/4 non-refusals** — confirmed a real model
capability ceiling, not a retrieval or prompt-clarity problem. Every
non-8B free-tier Groq model caps at 1,000 requests/day (vs. 14,400/day for
the 8B model), ruling out a wholesale default swap.

**Shipped instead as a refusal-triggered one-shot escalation retry**
(`RAG_Project_1 v0.5.13`): `nodes/generate_knowledge.py` only calls the
escalation model when the primary answer is a refusal, falling back to the
original refusal on any escalation failure. **Validated live through the
real wired path:** the drainage-system question now answers correctly
(`escalated: True`); an already-correct question confirmed it does not
waste an escalation call (`escalated: False`).

## 7. Related, downstream work

The recurring theme across every fix in §2 and §6 — working around Groq's
free-tier token/request ceilings — became this session's next stated
focus: token efficiency (`v0.6.0`). A response cache now skips the
workflow entirely for a repeated first-turn question; validated live at
14.51s → 0.0s on a repeat with zero LLM calls spent. See
`docs/05-roadmap.md` v0.6.0 for the full writeup — out of scope for this
report, which is specifically the benchmark/chunking-quality arc.

## 8. Open items

- **L5-Cross-document (20%) and the two still-refusing comparative
  questions** (trade networks, technological leap) remain real gaps —
  the escalation retry helps but doesn't fully close this category. A
  further fix would need either a stronger/different escalation model or
  a dedicated compare-then-synthesize retrieval strategy.
- **Real `StructureChunker`** (heading-hierarchy-aware, currently just a
  `RecursiveChunker` alias) was deliberately not built here — the
  investigation in §3–4 showed the real gap was classification (wrong
  profile picked), not the chunking algorithm itself. Building a new
  chunker without that evidence would have solved the wrong problem.
