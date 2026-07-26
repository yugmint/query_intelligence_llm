# 06 — Release Notes

[Keep a Changelog](https://keepachangelog.com/)-style, anchored on tags.
`v0.0.1` is the first tag this repo has — everything before it is
reconstructed from `git log` and grouped into the same phases as §10 of
`DOCUMENTATION.md`, without version numbers of its own (it was never
tagged at the time).

## [0.3.1] — 2026-07-26

Deployment-readiness push, part 2: fixed the concurrency crash found
while writing the performance/deployment-readiness report
(`docs/reports/2026-07-26-performance-and-deployment-readiness.md`).

**Fixed:**
- `src/retrieval/llm.py` — `LLMFactory` now attaches a client-side
  `InMemoryRateLimiter` (tuned to stay under Groq's 6,000 TPM ceiling
  for `llama-3.1-8b-instant`, with margin) plus `max_retries=3` and a
  30s `request_timeout` to the shared `ChatGroq` instance. Fixes a real,
  reproduced crash: 5 concurrent requests previously failed on request 2
  with an unhandled `groq.RateLimitError`. Re-ran the same scenario
  after the fix: no crash, requests queue and complete instead.
- `src/api.py` — `/query` now catches any exception that still reaches
  it (exhausted retries, or an unrelated bug) and returns a clean 503
  instead of an unhandled 500.

**Evaluated and explicitly rejected as alternatives:**
- Self-hosting an open-source model — doesn't fit the $0 budget in
  practice (moves cost to compute; CPU-only inference of an 8B+ model is
  dramatically slower than Groq's specialized hardware).
- Switching to Cerebras — blocked on this account's billing/org-type
  status (`402 Payment required` on every model), and its free tier is
  being retired 2026-08-17 regardless (card-on-file required after).
- Switching to Google Gemini — free-tier traffic may be used to improve
  Google's products; ruled unacceptable for a public-facing service.
  (Confirmed Groq itself already has a strict no-training policy, SOC 2
  Type II — staying on Groq turned out to be the most privacy-safe
  choice too, not just the simplest.)

## [0.3.0] — 2026-07-26

Deployment-readiness push: fixed the source-attribution/identity-question
gap that had been open since the reranking work, using
`ingestion_fixed` `v0.2.0`'s new section-role metadata.

**Fixed:**
- `src/workflow/nodes/rerank.py` — drops `is_reference_section` chunks
  from the candidate pool before scoring. Fixes the EfficientNet Q1
  failure mode (a References-section citation formatted like the
  document's own title, mistaken for it) for good: wrong → safe refusal
  → now fully correct. Full 10-question regression suites (Factor
  Analysis + EfficientNet): 20/20 correct, up from 16/20. Requires an
  index rebuilt with `ingestion_fixed >= v0.2.0` to take effect — older
  indexes won't have the metadata field and the filter silently no-ops
  (`document.metadata.get(...)` on a missing key).

**Investigated, prompt guideline added, gap remains:**
- The distractor-number bug (airlock paper, "what was the sample
  size?") was re-diagnosed: not a generation reading-comprehension gap
  as first thought, but a retrieval-ranking one -- the correct source
  sentence ranks #8/15 and never reaches the model. A general
  numeric-grounding instruction was added to
  `src/prompts/generation.py` anyway (harmless, may help elsewhere) but
  confirmed (3 repeated runs) not to fix this specific case. Tracked in
  `docs/05-roadmap.md`, not fixed.

## [0.2.2] — 2026-07-25

Fourth-document spot check (`airlock-on-edge_woolf_default_27.pdf`, a real
COVID-19 severity study) surfaced a `ingestion_fixed` classification bug
(fixed there, `v0.1.3`) and two generation/reranking-side findings on this
side. No production code changed here — findings and roadmap only.

**Found:**
- A chunk-boundary issue (title text glued onto an unrelated address
  block on a page with no blank-line paragraph breaks) that dropped the
  title/author chunk from the final reranked top-k for identity-type
  questions. A fix was built and verified against this document, but
  reverted after re-validation surfaced regressions on the already-shipped
  Factor Analysis/EfficientNet indexes — see
  `ingestion_fixed/docs/05-roadmap.md` v0.2.0 for the full writeup.
- A generation reading-comprehension gap: when both a correct chunk and a
  distractor chunk with similar-context numbers are retrieved together,
  generation can pick the wrong one even with the right answer present in
  context. New roadmap item, no fix attempted yet.

Full report: `docs/reports/2026-07-25-airlock-paper-e2e-test.md`.

## [0.2.1] — 2026-07-24

Follow-up to `v0.2.0`: closes the latency-measurement gap flagged in
`docs/reports/2026-07-24-reranking-validation.md` §5. No production code
changed.

**Added:**
- `scripts/measure_reranking_latency.py` — standalone benchmark comparing
  FAISS-alone (`k=TOP_K=3`, pre-reranking) against FAISS
  (`k=RERANK_CANDIDATES=15`) + cross-encoder rerank, against the same two
  real indexes/question sets used throughout the reranking validation
  report.

**Measured:**
- Reranking adds ~700-725ms per query on CPU (the cross-encoder forward
  pass over 15 candidates) — FAISS search itself is unaffected by the
  larger candidate count. Corrects §5's original "small model, probably
  fine" assumption, which was never actually measured. Full numbers and
  what to do if this becomes a problem: report §5.

## [0.2.0] — 2026-07-24

Intelligence layer, first item: reranking. First real feature addition
since the `v0.1.0` stabilization/polish pass — validated against actual,
previously-diagnosed failures rather than shipped on theory.

**Added:**
- `src/workflow/nodes/rerank.py` — new `rerank` node between `retrieve`
  and `generate`. Cross-encoder (`cross-encoder/ms-marco-MiniLM-L-6-v2`,
  via the already-present `sentence-transformers` dependency) scores
  `RERANK_CANDIDATES` (15) FAISS candidates against the query and keeps
  the top `TOP_K` (3) for generation.
- `src/retrieval/reranker.py` — `RerankerFactory` (singleton, lazy-loads
  the cross-encoder so importing the module doesn't force the
  import/download for callers that never rerank).
- `tests/test_node_rerank.py` + `FakeReranker` in `conftest.py` — 7 new
  unit tests, no real model load.

**Changed:**
- `src/retrieval/retriever.py` — `RetrieverFactory` now pulls
  `RERANK_CANDIDATES` from FAISS instead of `TOP_K`; the `rerank` node is
  what narrows it back down.
- `src/workflow/resources.py` — `RAGResources` gained a `reranker` field,
  built once in `build_resources()` alongside the other shared resources.
- `src/retrieval/config.py` — added `RERANK_CANDIDATES` (env-overridable,
  default 15) and `RERANK_MODEL`.

**Validated:**
- Re-ran the exact questions/indexes from both prior e2e reports with
  reranking in place: 5 of 6 previously-diagnosed failures fixed outright
  (both Factor Analysis retrieval misses; 3 of 4 EfficientNet failures).
  The 6th (a confidently-wrong answer — a References-section citation
  mistaken for the document's own title) is no longer wrong, though not
  yet fully correct either — converted to a safe refusal instead. Zero
  regressions across both full 10-question suites. Full writeup:
  `docs/reports/2026-07-24-reranking-validation.md`.

## [0.1.0] — 2026-07-24

Presentation & correctness polish — small, high-leverage fixes to make
what `v0.0.1` already did legible, not new features.

**Added:**
- "Proof It Works" section in `README.md` — a real, live-captured
  conversation transcript (greeting → knowledge → pronoun follow-up
  testing session-scoped memory/query rewriting → guardrail rejection),
  not hand-written or fabricated.

**Fixed:**
- `RAGState` declared `retrieved_documents`/`reranked_documents`, but
  `retrieve_context.py` had always written to an undeclared `documents`
  key instead. Renamed the declared field to `documents` to match
  reality; `reranked_documents` will come back for real once reranking
  (v0.2.0) exists. See `07-design-decisions.md`.
- Removed the unused `openai` dependency from `requirements.txt`
  (confirmed unreferenced anywhere in `src/`; Groq via `langchain-groq`
  is the actual LLM provider).

## [0.0.1] — 2026-07-24

First tagged version — a direct answer to "is this prod-level yet" (no)
turned into a full stabilization pass. Commits `cd018dc` through the tag,
on top of `aa19c6c` below.

**Fixed:**
- The stale-index problem, for real, not just cosmetically. Rebuilt the
  FAISS index with the current `ingestion_fixed` pipeline rather than
  repointing at the newer-looking `vectorstore/` build, which turned out
  to have the exact pre-fix chunking/metadata bugs `ingestion_fixed`
  exists to fix (confirmed by direct `index.pkl` inspection: avg 64-char
  chunks, `document_type: 'pdf'` everywhere). Old index directories
  renamed aside for comparison, then deleted once verified. Full story in
  §8 of `DOCUMENTATION.md`. (`cd018dc`)
- Per-session conversation memory — `RAGResources` no longer holds
  `memory`; it's keyed by `session_id` in `RAGService` and carried through
  `RAGState["session_memory"]` per request. Uncovered a much bigger bug in
  the process: `chat_history` was hardcoded to `""` on every call and
  never actually populated from memory — conversation context had **zero
  effect** on behavior before this fix, in any session configuration.
  `src/utils/chat_history.py::format_chat_history` existed but was never
  called from the live workflow. Verified fixed end-to-end. (`0eeae75`)
- A `StateGraph` node/state-key collision (`"intent"` used as both a node
  id and a state field) that made the graph fail to even *build* under
  the `langgraph` version actually installed here — first time this
  workflow had run end-to-end in this dev environment. (`0eeae75`)
- A whitespace-based prompt-injection detection bypass: extra internal
  spaces in a blocked phrase (`"ignore   previous   instructions"`) evaded
  every pattern, since `PromptInjectionValidator` ran before
  `QueryNormalizer` in the chain. Fixed by matching a whitespace-collapsed
  copy internally, without reordering the chain. (`86aeb21`)

**Added:**
- Standalone FastAPI service (`src/api.py`): `GET /health`, `POST /query`
  (with `session_id`), `POST /reload` (in-place FAISS reload, no restart),
  `POST /reset-memory` — all but `/health` behind `X-API-Key` auth
  (`RAG_API_KEY`). Deployable alongside `ingestion_fixed`'s own API over a
  shared FAISS volume (`docker-compose.yml`). (`1e482e4`)
- `Dockerfile` (none existed before). (`1e482e4`)
- Full pytest suite: 57 tests — all 5 guardrail validators, the chain's
  ordering/short-circuit behavior, and all 7 workflow nodes, with fake
  LLM/retriever (`tests/conftest.py`) and no real network calls.
  (`79b40bd`)
- Full documentation set: `DOCUMENTATION.md` + numbered `docs/`.
  (`42d4200`)

**Changed:**
- `src/retrieval/config.py`'s `FAISS_PATH` reads `FAISS_INDEX_PATH` env
  var instead of being hardcoded. (`cd018dc`)
- `src/retrieval/llm.py`'s `LLMFactory` accepts `GROQ_API_KEY` from the
  environment directly, without requiring `cred.json`. (`1e482e4`)
- `requirements.txt` — `langgraph` pinned to `0.2.76` (previously
  unpinned/missing entirely; `>=0.3` conflicts with this project's
  `langchain-core` pin); `fastapi`/`uvicorn` corrected to the versions
  actually verified working (`0.139.2`/`0.51.0`). (`1e482e4`)

## `aa19c6c` (2026-07-24) — Remove in-tree ingestion pipeline

Committed the `src/ingestion/` deletion (16 files) and
`test/cuda_test.py`/`test/exp_notebook.ipynb` that had sat uncommitted for a
while — see `04-contributing.md`'s Git hygiene section for why that was a
problem in its own right. `git log` and the working tree now agree that
this repo has no ingestion code.

## 2026-07-16 — New ingestion pipeline (later removed from this repo)

- `5e12446` (HEAD as of last commit) — Added a full modular ingestion
  package under `src/ingestion/` (loaders, cleaners, chunkers, embedders,
  indexers, metadata) plus validation/benchmark scripts, and landed query
  rewriting (`src/processing/query_rewriter.py`,
  `src/workflow/nodes/process_query.py`) in the same commit. This ingestion
  code was later removed from the working tree (see Unreleased, above) and
  spun off into the standalone `ingestion_fixed` project — see §8 of
  `DOCUMENTATION.md` for the full history.

## 2026-07-15 — Guardrails + full modular LangGraph workflow (Phase 1 complete)

- `bd797f6` — README updated to mark Phase 1 (production RAG workflow)
  complete. Natural tag point that was never tagged.
- `dbcc9fd` — **feat:** modular LangGraph workflow with input guardrails —
  the node/routing architecture described in `01-architecture.md`, largely
  as it exists today.
- `27e969e` — Refactored factories, debugging improvements, CUDA support
  for the embedding model.

## 2026-07-14 — LangGraph hardening, testing, observability

- `b642bde` — Fixed intent node for greeting/chit-chat routing.
- `a65328c` — Logger function updated.
- `422151c` — Codebase cleanup.
- `1e5ed5d` — Added a test runner for unit testing and reporting (the
  ancestor of today's `src/evaluation/runner.py`).
- `c04f0c7` — Workflow updated for "LangGraph phase-1" (commit message has
  a typo — see `04-contributing.md`'s Git hygiene section).
- `34c4714` — `requirements.txt` updated alongside nodes/graph directory
  restructuring.

## 2026-07-08 — LangGraph foundation

- `46137e0` — Merge remote changes.
- `9719177` — Added LangGraph foundation: shared `RAGState` and
  `RAGResources` container — the point where this stopped being a single
  `RAGPipeline` class (`rag_pipeline_archived.py` — dead code by this point;
  removed entirely in the 2026-07-24 cleanup pass, recoverable via git
  history if ever needed) and became a graph of nodes.

## 2026-05-07 — Ingestion/retrieval split, iterative hardening (pre-LangGraph era)

- `cb1b1ee`, `5cd05ef`, `4ab18d5`, `74bd882`, `97bcde1`, `644b461`,
  `081367a` — reference fixes, `main.py` fixes, removing a redundant LLM
  call in intent classification, JSON-structured response format.
- `73c59e0` — "seperated the ingestion and retiveal pipelines" — flat `src/`
  reorganized into `src/ingestion/` (a placeholder, committed fully
  commented out — see `04-contributing.md`'s Git hygiene section) and
  `src/retrieval/` (the working LangChain pieces, still the retrieval
  layer's structure today).
- `0851534` — Resolved a `.gitignore` merge conflict.
- `552be68`, `eea561b` — README revisions, removed promotional content.
- `9b117d5` — `.gitignore` updated to ignore `cred.json` (before any secret
  had a chance to leak).
- `e5eef3f` — `venv_rag` ignored.
- `69f534a` — Initial commit.

## Documented but not in this repo's git history

The pre-`73c59e0` "monolithic script era" (a single flat `src/` with
`ingestion_pipeline.py` and `rag_pipeline.py`) isn't reconstructable from
`git log` — it predates or was squashed into the initial commit. It used to
be described in `local/project_history/README_v3.md`, an untracked local
file that was permanently deleted in a 2026-07-24 cleanup pass (not
git-recoverable — it was gitignored, never committed). What's written about
that era in `DOCUMENTATION.md` §1/§8 is a paraphrase from a reading of that
file earlier the same session, not a verbatim record.
