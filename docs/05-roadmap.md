# 05 — Roadmap

Versioned by milestone (semver, pre-1.0 — `0.MINOR.0` for a meaningful
batch of work, `0.0.PATCH` for small fixes between them). First tag is
`v0.0.1`, not `v1.0.0`: unlike the sibling `ingestion_fixed` (already
considered stable, tagged `v1.0.0`), this repo is still actively changing
and hasn't earned a 1.0 claim yet. See `06-release-notes.md` for the
per-version changelog this file's "Shipped" sections are summarized from.

The root `README.md`'s 5-phase roadmap (Production RAG Workflow →
Intelligence Layer → Advanced Retrieval → Enterprise Features → Agentic
Intelligence) is the long-arc framing; the versions below are how that
actually gets delivered incrementally.

---

## v0.0.1 — Stable baseline (2026-07-24)

First tagged version. Everything here was broken, missing, or undocumented
before this session; all of it is now fixed and covered by tests.

**Shipped:**
- Fixed the stale FAISS index (was serving from a May-era build; the
  newer-looking alternative was actually worse — pre-fix chunking/metadata
  bugs). Rebuilt with the current `ingestion_fixed` pipeline.
  `FAISS_PATH` is now configurable via `FAISS_INDEX_PATH` instead of
  hardcoded.
- Per-session conversation memory, plus a much bigger bug found in the
  process: `chat_history` was hardcoded to `""` on every call and never
  actually populated from memory — conversation context had **zero
  effect** on behavior, in any session configuration, before this fix.
- Fixed a `StateGraph` node/state-key collision (`"intent"` used as both a
  node id and a state field) that made the graph fail to *build* under the
  `langgraph` version actually installed here — first time this workflow
  had been run end-to-end in this dev environment.
- Standalone FastAPI service (`src/api.py`) with `X-API-Key` auth,
  deployable alongside `ingestion_fixed`'s own API over a shared FAISS
  volume (see the top-level `docker-compose.yml`).
- Removed the in-tree ingestion pipeline for good (`aa19c6c`) — superseded
  by the standalone `ingestion_fixed` project.
- Full pytest suite: 57 tests — all 5 guardrail validators, the chain's
  ordering/short-circuit behavior, and all 7 workflow nodes, with fake
  LLM/retriever (no real network calls).
- Fixed a real security gap found while writing those tests: whitespace
  padding inside a blocked phrase (`"ignore   previous   instructions"`)
  was bypassing prompt-injection detection entirely.
- Full documentation set: `DOCUMENTATION.md` + numbered `docs/`
  (architecture, RAG-specific best practices, development guide,
  contributing, roadmap, release notes, design decisions).

**Known limitations carried into v0.1.0+** (not blockers for calling this
a stable baseline, just not yet done):
- Session memory has no persistence or eviction/TTL — an in-memory dict,
  fine for moderate traffic, not for long-running high-volume use.
- No rate limiting on the API.
- `openai` is listed in `requirements.txt` but nothing uses it (Groq via
  `langchain-groq` is the actual provider).

---

## v0.1.0 — Presentation & correctness polish (2026-07-24)

Small, high-leverage fixes to make what's already true legible — not new
features. All three shipped in the same session as `v0.0.1`.

- [x] A real example conversation/transcript in the README — captured
      live against `v0.0.1` (greeting → knowledge → pronoun follow-up →
      guardrail rejection), not hand-written. See "Proof It Works" in
      `README.md`.
- [x] Reconcile `RAGState`'s `retrieved_documents`/`reranked_documents`
      vs. what `retrieve_context.py` actually writes — renamed the
      declared field to `documents`. See `07-design-decisions.md`.
- [x] Removed the unused `openai` dependency — confirmed unreferenced
      anywhere in `src/` (Groq via `langchain-groq` is the actual provider).

## v0.2.0 — Intelligence layer (README Phase 2)

- [x] **Reranking after initial FAISS retrieval — shipped and validated
      2026-07-24.** `RetrieverFactory` now pulls `RERANK_CANDIDATES=15`
      chunks from FAISS instead of `TOP_K=3`; a new `rerank` node
      (`src/workflow/nodes/rerank.py`) scores them with a cross-encoder
      (`cross-encoder/ms-marco-MiniLM-L-6-v2`, via the already-present
      `sentence-transformers` dependency) and keeps the top `TOP_K=3` for
      generation. Directly fixed 5 of the 6 real failures identified in
      `docs/reports/2026-07-24-academic-document-e2e-test.md` and
      `docs/reports/2026-07-24-efficientnet-research-paper-e2e-test.md`
      (re-tested, same questions, same indexes — not just theorized to
      help): both Factor Analysis retrieval misses, and 3 of 4 EfficientNet
      failures including converting the one confidently-wrong answer into
      a safe refusal. Zero regressions across both 10-question suites.
      Full validation: `docs/reports/2026-07-24-reranking-validation.md`.
      Design rationale (why a cross-encoder, why 15 candidates, why not
      reorder the graph differently): `07-design-decisions.md`.
- [ ] Metadata-aware retrieval — filter by `document_type`, source, etc.
      The ingestion side already attaches this metadata per chunk;
      nothing here queries on it yet.
- [ ] Better chunk selection / dedup at the `retrieve` node. Partially
      addressed by reranking (a cross-encoder naturally down-ranks
      near-duplicate/redundant chunks relative to a genuinely distinct
      relevant one), but no explicit diversity constraint exists yet —
      keep as a smaller follow-up, not urgent given reranking's results.
- [x→⚠️] **Source-attribution failure, partially resolved.** The
      EfficientNet report's Q1 (confidently wrong answer, a References-
      section citation mistaken for the document's own title) is no
      longer *wrong* after reranking — it now safely refuses. It's still
      not *correct*, though: reranking's cross-encoder still doesn't
      reliably surface the actual title-page chunk for identity-type
      questions ("what is this document called"). See
      `docs/reports/2026-07-24-reranking-validation.md` §4 for why this
      needs a different mechanism than topical-relevance reranking —
      likely explicit chunk-level section-role metadata (references vs.
      body vs. title/abstract) from the ingestion side, or a dedicated
      "about this document" query path that doesn't rely on similarity
      search at all. Not closing this item; downgrading its severity.
- [ ] **Generation picks the wrong number when a distractor with
      similar context is also in the retrieved chunks** — found
      2026-07-25 testing a fourth real document (Hu et al. 2020,
      COVID-19 severity study). Asked "what was the sample size?"; the
      correctly-retrieved chunk (*"A total of 40 patients were
      enrolled in this study"*) **and** a distractor chunk from the
      paper's own Limitations section (*"There were a total of 120
      COVID-19 patients in Xi'an City, and only 40 of them were treated
      in our center"*) both made the final reranked top-k. The model
      answered "120" — picking the wrong number despite the right one
      being present in the same context. Not a retrieval failure (both
      the right and wrong answer were retrieved); a generation
      reading-comprehension gap. No fix attempted yet — candidates worth
      trying: prompting the model to quote/cite the exact source
      sentence before stating a number, or a numeric-fact verification
      pass on the final answer. Full trace:
      `docs/reports/2026-07-25-airlock-paper-e2e-test.md`.

(Query rewriting — `QueryRewriter` / `process_query` — already shipped,
landed in commit `5e12446`.)

## v0.3.0 — Advanced retrieval (README Phase 3)

- [ ] Hybrid search (BM25 + dense).
- [ ] Parent-child retrieval, context compression.

## v0.4.0 — Multi-user & production hardening

- [ ] Persistent, bounded session memory (replace the in-memory dict; cap
      or summarize long conversations).
- [ ] Rate limiting on the API.
- [ ] Auto-trigger `/reload` from the ingestion side after a successful
      `/ingest`, instead of requiring a manual call (see the shared
      `docker-compose.yml`'s comments — deliberately not built yet).
- [ ] Make `RAGService` tolerate "no index yet" at startup instead of
      crash-looping against an empty shared volume.

## v0.5.0 — Enterprise features (README Phase 4)

- [ ] Source citations in generated answers.
- [ ] Streaming responses.
- [ ] Observability / metrics dashboard beyond structured logs and
      evaluation CSVs.
- [ ] Expanded guardrails: PII detection, toxicity detection, language
      detection, sensitive-info detection, role validation (current chain
      is empty/length/character/prompt-injection/normalization only).

## Unscheduled

- [ ] CI (GitHub Actions): run `pytest tests/ -v` on every push.
- [ ] Agentic Intelligence (README Phase 5) — multi-agent, tool calling,
      web search. Deliberately not scheduled into a version yet; too far
      out to commit to a shape.
