# End-to-End Test Report — Fourth Document (Structured-Abstract Clinical Paper)

**Date:** 2026-07-25
**Document:** `airlock-on-edge_woolf_default_27.pdf` — actually **"Early
prediction and identification for severe patients during the pandemic of
COVID-19: A severe COVID-19 risk model constructed by multivariate logistic
regression analysis"** (Hu et al., *Journal of Global Health*, Dec 2020),
12 pages, a real clinical study with a **structured abstract**
(Background/Methods/Results/Conclusions — no literal word "Abstract").
**Pipeline versions:** `ingestion_fixed` `v0.1.2` → `v0.1.3` (this report
found and fixed the bug that bumped it), `RAG_Project_1` `v0.2.1`
**Why this document:** requested as a quick spot-check of the full engine
(ingestion + retrieval) on a new real document. Turned out to exercise a
document layout none of the prior three had: a structured abstract with no
literal "Abstract" heading, and a front-matter block with zero blank-line
paragraph breaks.

**Method:** same standard as prior reports — every number below is real,
captured output. Isolated index at `local/test_reports/airlock_index/`
(gitignored), separate from production and the other three test indexes.

---

## 1. Ingestion — found a real misclassification

First ingestion run classified the document `legal` at 0.85 confidence.
Root-caused to two compounding bugs in `PDFAnalyzer._classify_document`:

1. The paper's structured abstract (Background/Methods/Results/
   Conclusions) never uses the literal word "Abstract" — common in medical
   journals — so the `research_paper` rule never fired.
2. It fell through to `legal`'s bare `"agreement" in text` check, which
   matched inside *"...crude **agreement** were all over 85%"* — a
   statistics term (inter-rater agreement), not a legal one.

**Fixed in `ingestion_fixed` `v0.1.3`:** `research_paper` now also fires on
>=3 of {background, objective(s), methods, results, conclusion(s)}
appearing together (still requires `layout.has_references`); `legal` now
requires an actual legal-agreement phrase instead of the bare word.
Re-ingesting the same PDF after the fix: `research_paper`, confidence 0.90,
`chunk_size=630` (was `legal`, 0.85, `chunk_size=1400`). Two new regression
tests added. Full details: `ingestion_fixed/docs/05-roadmap.md` v0.2.0.

---

## 2. Retrieval/generation — 6-question spot check

Ran through the full compiled graph (guardrails → intent → retrieval →
rerank → generation), before and after the classification fix.

| # | Question | Before (legal, 1400) | After (research_paper, 630) |
|---|---|---|---|
| 1 | Title and authors? | ✅ Correct, full names | ⚠️ Regressed — see §3 |
| 2 | Sample size and design? | ✅ Correct — 40 patients, retrospective | ❌ Regressed — see §3 |
| 3 | Sensitivity/specificity? | ✅ Correct — 90.5%/84.2% | ✅ Correct (unchanged) |
| 4 | Independent risk factors? | ✅ Correct | ✅ Correct (unchanged) |
| 5 | Imaging modality? | ✅ Correct, verified against a table footnote | ✅ Correct (unchanged) |
| 6 | "What is this document about?" | ✅ Correct summary | ✅ Correct summary |

The classification fix is unambiguously correct and shipped. But
re-running the same 6 questions against the resulting (smaller,
differently-bounded) chunks exposed two pre-existing weaknesses that the
old, wrong `legal`/1400-char chunking happened to paper over by accident.

## 3. Two findings exposed by the (correct) rechunking

**Q1 — title/author chunk dropped from final top-k.** The title+author
chunk *was* in the FAISS top-15 (rank 9/84 by similarity), but the chunk
boundary landed mid-block: PDF extraction left only a single `\n` between
the correspondence email and the actual title, so the chunk read
*"...China 82399536@qq.com Early prediction and identification for
severe..."* — the title glued onto the tail of an address block. The
cross-encoder reranker scored this noisy, mixed-content chunk below a
cleaner "Authorship contributions" section on page 11, dropping it from
the final top-3. Result: an honest *"I don't know"* / partial-initials
answer instead of the full title and author names.

**Q2 — generation picked the wrong number from a distractor.** The model
answered "120 patients" instead of "40". **Correction (2026-07-25, later
same day):** originally diagnosed as a generation reading-comprehension
gap (assumed both the correct chunk and the distractor were in context).
Traced the actual context: the clean sentence (*"Results: A total of 40
patients were enrolled in this study, of whom 19 were mild and 21 were
severe"*) ranks #8/15 after reranking and never reaches the `TOP_K=3` cut
— the model only ever saw the ambiguous Limitations-section sentence
(*"There were a total of 120 COVID-19 patients in Xi'an City, and only 40
of them were treated in our center"*). This is a retrieval-ranking
problem, not a generation one — no prompt fix can ground an answer in text
the model never received (tried anyway, confirmed no effect via 3 repeated
runs). Tracked in `RAG_Project_1/docs/05-roadmap.md` v0.2.0.

## 4. Chunk-boundary fix attempted and reverted

Built a fix for the Q1 boundary issue: a `TextCleaner` rule inserting a
paragraph break after email addresses, plus a paragraph-aware
`RecursiveChunker._pack()` that refuses to glue a new paragraph onto the
remnant of a force-split one. Verified it fixed this document's chunk
boundary as intended (title no longer glued to the address block).

**Re-validated against the two already-shipped indexes (Factor Analysis,
EfficientNet — see
[2026-07-24-reranking-validation.md](2026-07-24-reranking-validation.md))
before shipping, per standing practice for any change to shared chunking
logic.** Factor Analysis's 10-question suite held up (Q6 even improved).
EfficientNet regressed on 2 of 10 previously-correct answers (Q5 "baseline
network design method" and Q9 "other networks scaled" both started
answering incorrectly — traced to the same shared source passage on page 1
no longer landing in the retrieved context). **Reverted rather than ship a
net-negative change.** `ingestion_fixed`'s `RecursiveChunker`/`TextCleaner`
are back to their pre-2026-07-25 state; only the classification fix
shipped (`v0.1.3`). Full writeup and lesson learned:
`ingestion_fixed/docs/05-roadmap.md` v0.2.0.

Worth noting even setting the regression aside: with the boundary fixed,
the cross-encoder reranker *still* ranked the correct title chunk only
#12/15 for a "title and authors" query. This may not be fully fixable on
the chunking side alone — consistent with the identity/self-referential
question gap already tracked in
[2026-07-24-reranking-validation.md](2026-07-24-reranking-validation.md) §4.

## 5. Recommendation

Ship the classification fix (done, `v0.1.3`) — it's an unambiguous,
well-tested correctness improvement with no chunking-side risk. Don't
re-attempt the chunk-boundary fix without a stronger design than "prefer
not to glue a new paragraph onto a force-split remnant" — that heuristic
is too coarse; whoever picks this up should look at fixing it at the
source (better paragraph-structure preservation during PDF extraction, not
post-hoc chunker heuristics) rather than iterating further on `_pack()`.

**Update (2026-07-26):** the broader identity-question gap this report
fed into got a real, general fix — `ingestion_fixed` `v0.2.0`'s
`is_reference_section` metadata, consumed by `RAG_Project_1` `v0.3.0`'s
`rerank` node. It fully fixed the EfficientNet paper's equivalent
question (was safe-refusal, now exactly correct) and re-validated clean
across both previously-shipped 10-question suites (20/20). It does
**not** fix this document's Q1, though — the airlock paper's title/author
retrieval problem was always the separate chunk-boundary issue above
(reverted, not this one), so it still safely refuses. Q2's
distractor-number issue was re-diagnosed as retrieval-ranking, not
generation, and remains open — see `docs/05-roadmap.md`.
