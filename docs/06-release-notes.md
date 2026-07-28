# 06 — Release Notes

[Keep a Changelog](https://keepachangelog.com/)-style, anchored on tags.
`v0.0.1` is the first tag this repo has — everything before it is
reconstructed from `git log` and grouped into the same phases as §10 of
`DOCUMENTATION.md`, without version numbers of its own (it was never
tagged at the time).

## [0.5.13] — 2026-07-28

**Added:**
- Refusal-triggered escalation retry. `nodes/generate_knowledge.py`
  retries once with `openai/gpt-oss-20b`
  (`LLMFactory.get_escalation()`) only when the primary
  `llama-3.1-8b-instant` answer looks like a refusal -- confirmed by a
  real test that this model answers comparative questions ("which X
  had more/better Y") the primary model can't, from the same context.
  Falls back to the original refusal on any escalation failure. New
  `src/processing/refusal_detector.py` (promoted out of
  `scripts/benchmark.py`, now shared).

**Validated:** the drainage-system question that regressed in 0.5.12
now answers correctly through the real wired path; a confirmed
already-correct question does not trigger an unnecessary escalation
call. 8 new tests.

## [0.5.12] — 2026-07-28

**Fixed:**
- `scripts/benchmark.py`: `_HISTORY_INDEX` repointed to the
  reclassified index (see `ingestion_fixed` v0.4.8 -- numbered-outline
  TOC detection); one more grading-gap fix ("Mauryas" vs. the narrow
  `"mauryan"` keyword).

**Result:** full 92-question History-Book-only real re-run: 82% -> 85%
answer correctness. Mixed underneath, not a clean win -- L1-Exact Fact
+15pp and L5-Ambiguous +20pp are real fixes; L5-Cross-document -20pp is
a real, traced regression (comparative "which X vs Y" questions get
refused regardless of chunk size -- a generation-behavior gap, tracked
separately). See `docs/05-roadmap.md` for the full breakdown.

## [0.5.11] — 2026-07-28

**Fixed:**
- Intent detection no longer calls the LLM. `route_by_intent` only ever
  used the result as a binary knowledge/conversation switch, so the
  3-way LLM classification was answering a question nobody downstream
  needed at that resolution -- and it was burning a second token per
  query from the shared rate-limiter bucket
  (`InMemoryRateLimiter(requests_per_second=0.08, max_bucket_size=2)`),
  which refills at 1 token/~12.5s. New
  `src/processing/intent_classifier.py`: anchored regex classification,
  biased toward "knowledge" as the safe default. 11 new/rewritten
  tests, including a regression guard against the real 97-question
  benchmark set.

**Validated:** timed the same 10 real benchmark questions against live
Groq calls before/after -- mean latency 25.04s -> 12.68s (49%
reduction).

## [0.5.10] — 2026-07-28

**Added:**
- `scripts/benchmark.py` extended to all 97 cases across L1-L6 plus
  Manual Spot-Check (was 22 graded cases), ground-truthed against the
  real source PDF.

**Result:** 82% answer correctness, 10% potential hallucination, 100%
citation accuracy (3 judgeable), mean latency 25.04s. Weakest
categories: L5-Cross-document (40%) and L5-Ambiguous (60%, 40%
hallucination) -- both by design the hardest cases in the set. See
`docs/05-roadmap.md` v0.4.0 for the full per-level breakdown.

## [0.5.9] — 2026-07-28

**Changed:**
- Parent-child retrieval redesigned: replaced full-parent-page
  expansion with expansion by `chunk_id` neighbors
  (`PARENT_CONTEXT_NEIGHBOR_CHUNKS`, default 1 each side). The v1
  page-based approach was found to provide near-zero benefit on real
  book-length documents (dense pages exceeded its size cap almost
  every time -- see `docs/05-roadmap.md` v0.3.0). Bounded by chunk
  count instead of page size, so it's no longer at risk of the 413
  that motivated the old cap in the first place. 7 rewritten tests.

**Validated:** re-tested against the same real 117-page book --
expansion genuinely active again (1,418 → 4,581 chars on a real query,
vs. zero growth under v1); numeric-widened path (the original 413
trigger) still clean; zero regressions on the same 5-question set from
the earlier E2E report.

## [0.5.8] — 2026-07-28

**Added:**
- Parent-child retrieval. `expand_to_parent_context` builds generation
  context from each matched chunk's full parent page (looked up in the
  vectorstore's own docstore by source+page_number -- no separate
  parent store, no ingestion-side changes) instead of just the small
  matched chunk. `documents`/citations stay scoped to what actually
  matched. 10 new tests.

**Fixed:**
- A real Groq 413 found during validation: `TOP_K_NUMERIC=8` chunks
  each expanding to a full dense page exceeded the 6000 TPM hard
  ceiling on one real query. New `PARENT_CONTEXT_MAX_CHARS_PER_PAGE`
  cap -- a page over budget falls back to the matched chunk alone
  rather than a truncated slice that could cut out the relevant part.

**Validated:** confirmed expansion is genuinely active on real data
(1,495 → 7,203 chars); full 26-question regression suite re-run after
the size-cap fix -- zero regressions, no more 413s.

## [0.5.7] — 2026-07-27

**Added:**
- `SensitiveInfoValidator` (email/SSN/phone/API-key regex + Luhn-checked
  card numbers) and `ToxicityValidator` (wordlist) added to the input
  guardrail chain. 12 new tests.

**Not built:** language detection and role validation, from the same
roadmap line -- no role/RBAC model exists in this codebase, and no
stated need to restrict languages. See `docs/05-roadmap.md` v0.5.0.

## [0.5.6] — 2026-07-27

**Added:**
- Observability. New `GET /metrics` (Prometheus text format,
  auth-protected): `rag_node_duration_seconds`/`rag_node_failures_total`
  per LangGraph node (hooked into the existing `log_node` decorator --
  no per-node instrumentation needed), `rag_requests_total` by endpoint
  + outcome, `rag_active_sessions`. New
  `RAGService.active_session_count()`.
  `../frontend/dashboard.html` -- a second buildless static page
  (same visual system as `index.html`) that polls `/metrics` and
  renders stat cards + per-node latency + request-outcome tables, with
  its own settings drawer and auto-refresh.
  18 new unit tests. New explicit dependency: `prometheus_client`
  (was already transitive, now pinned directly).

**Validated:** sent real traffic to a live server and confirmed
`/metrics`'s raw output correctly reflected exact request/session
counts and real per-node latency; Playwright confirmed
`dashboard.html`'s rendered values match the raw metrics output
exactly, in both themes.

## [0.5.5] — 2026-07-27

**Added:**
- Streaming responses. New `POST /query/stream` (Server-Sent Events)
  alongside the unchanged `/query`. `RAGService.ask_stream()` streams
  via LangGraph's `stream_mode=["messages", "values"]` over the same
  compiled graph `ask()` uses, filtered to only forward
  `generate`/`conversation` node tokens. Mid-stream failures are
  signaled as an in-band `{"type": "error"}` event (can't fall back to
  a 503 once the stream has started). `../frontend/index.html` now
  renders the assistant's reply incrementally as tokens arrive.
  13 new/rewritten unit tests.

**Fixed:**
- `nodes/generate_conversation.py` asked the model to wrap replies in
  `{"response": "..."}` JSON, which would leak raw JSON syntax into a
  streamed response. Rewritten to ask for plain text, matching
  `generate_knowledge.py`'s prompt (which already showed the JSON-
  wrapper instruction wasn't reliably honored in the first place).

**Validated:** real token-by-token SSE delivery confirmed via a
timestamped client against a live server; Playwright confirmed the
frontend renders incrementally (sampled message length every 150ms
during a real request: 0 → 78 → 466 chars), not a single final paint.

## [0.5.4] — 2026-07-27

**Added:**
- Hybrid search (BM25 + dense). New `src/retrieval/bm25.py::BM25Factory`
  (`langchain_community.retrievers.BM25Retriever`, new `rank_bm25`
  dependency) built from the vectorstore corpus, fused with the
  existing dense retriever via Reciprocal Rank Fusion
  (`src/retrieval/hybrid.py`, `k=60`) before reranking. `RAGResources`
  gained `bm25_retriever`, rebuilt alongside the vectorstore on every
  `reload_index()`. Deliberately scoped to the plain retrieval path
  only -- metadata-filtered and numeric-question queries are
  unaffected, see `docs/05-roadmap.md` v0.3.0 for why. 15 new unit
  tests.

**Validated:** confirmed fusion is genuinely active on real data (not
a no-op) -- changed the top-3 candidate ranking for 3/3 plain
questions tested on the Factor Analysis index, correctly promoting a
definitional chunk dense-only search had buried under a boilerplate
header chunk. Full 26-question regression suite re-run through
`RAGService.ask()` end-to-end: zero regressions.

## [0.5.3] — 2026-07-27

**Added:**
- Source citations. `/query` now returns `citations`: one entry per
  distinct `(source, page)` pair among the chunks actually handed to
  generation, in relevance order (`src/services/citations.py`). New
  `Citation` pydantic model (`{source, page}`) in `src/api.py`.
  Deliberately chunk-provenance, not verified per-claim attribution --
  see `docs/05-roadmap.md` v0.5.0 for why self-reported inline
  citation markers were considered and rejected.
  `../frontend/index.html` renders it as a `sources:` line.
  15 new unit tests.

**Validated:** real query against the live API returned correct
page-level citations matching the actual source pages; verified on
both the plain and metadata-filtered retrieval paths; Playwright
screenshot confirms frontend rendering end-to-end.

## [0.5.2] — 2026-07-27

**Added:**
- Chunk dedup/diversity at rerank (`nodes/rerank.py::_select_diverse_top_k`):
  skips a candidate that's a near-duplicate (`difflib.SequenceMatcher`
  ratio >= `CHUNK_DEDUP_SIMILARITY_THRESHOLD`, default 0.8) of one
  already selected, letting a genuinely distinct lower-scoring chunk
  fill that TOP_K slot instead of two near-identical chunks both
  landing in it. 11 new unit tests.

**Validated:** full 26-question regression suite re-run at the
retrieve+rerank level — dedup never fired (no natural near-duplicates
in the existing three documents), zero regressions. Directly confirmed
the mechanism against the real failure mode it targets: re-ingested
`Factor_Analysis.pdf` a second time into a scratch index copy (real
duplicate ingestion) and re-ran a query — correctly skipped 2
literal-duplicate candidates, returning 3 distinct chunks. Full
writeup: `docs/05-roadmap.md` v0.2.0.

## [0.5.1] — 2026-07-27

**Added:**
- Dedicated numeric-question retrieval path (`src/processing/numeric_question.py`)
  for the previously-documented "distractor-number ranking gap": a fast,
  deterministic pattern match (no extra LLM call) widens the candidate
  pool (`RERANK_CANDIDATES_NUMERIC=80`) and `TOP_K` (`TOP_K_NUMERIC=8`)
  only for questions asking for a specific number, reusing the same
  direct-vectorstore path `v0.5.0`'s metadata filtering added. Non-numeric
  queries are completely unaffected. Strengthened the generation prompt's
  existing distractor-number guideline to explicitly prefer a total that
  breaks down into consistent subgroups over one naming a broader
  background population.
- 25 new unit tests (detector + both nodes' widening branches).

**Investigated more deeply, found worse than previously documented:**
re-reproducing the original 2026-07-25 failure fresh showed the correct
chunk isn't a near-miss at the default candidate pool — pure FAISS
similarity search ranks it 65th of 84 chunks in the document, and even
widening to nearly the full document only gets the cross-encoder to
rank it #8.

**Validated:** the exact originally-reported question now answers
correctly, 3/3 consistent runs. Full 26-question regression suite
(Factor Analysis + EfficientNet + the original failing document)
re-run: zero regressions, one additional real improvement. **Known
limitation:** a compound rephrasing of the same question ("...and
study design?") still gets the wrong answer — the fix narrows the
failure mode, it doesn't eliminate it. Full writeup:
`docs/05-roadmap.md` v0.2.0.

## [0.5.0] — 2026-07-27

**Added:**
- Metadata-aware retrieval filtering. `/query` accepts an optional
  `source` field (`RAGService.ask()`'s new `metadata_filter` param)
  to scope a question to one previously-ingested document instead of
  searching the whole index — matters now that ingestion is additive
  (v0.4.0) and one index can hold several unrelated documents.
  `nodes/retrieve_context.py` calls `vectorstore.similarity_search`
  directly when a filter is present (FAISS's own native metadata
  filter support), falling back to the existing pre-built retriever
  unchanged when it isn't. New `GET /sources` endpoint
  (`RAGService.list_sources()`) so a caller can discover valid
  `source` values instead of guessing a filename.
- 8 new unit tests covering the filter-branching retrieval path,
  `ask()`'s filter threading, and `list_sources()`.

**Validated:** real embeddings, real shared 2-document FAISS index
("Grandma's Bag of Stories" + `Factor_Analysis.pdf`) — `list_sources()`
correctly reports both documents' chunk counts; a question scoped via
`source` filter to the *wrong* document correctly retrieves zero chunks
and gets a safe "I don't know" instead of leaking the other document's
content. Full suite: 90/90 passing.

## [0.4.4] — 2026-07-27

Docs only — no code changed. `docs/05-roadmap.md` was missing four
already-shipped items entirely (they landed as fixes/additions in the
course of other work, without a corresponding checkbox): the query
rewriter recency fix, CORS middleware, the new `../frontend`, and the
optional local GPU acceleration docs. Added all four in their proper
places (query rewriter under v0.2.0, CORS under v0.4.0, frontend + GPU
under a new "Local tooling" section for work that doesn't fit the
5-phase customer-facing framing) so the roadmap accurately reflects
what's actually been built.

## [0.4.3] — 2026-07-26

**Added:**
- `src/api.py` — CORS middleware (`CORSMiddleware`, wide open by
  default, `CORS_ALLOW_ORIGINS` env override). Without this, browsers
  silently block every request from any frontend not served from this
  exact origin -- including the new `../frontend/index.html`, opened as
  a plain `file://` page. Found necessary while wiring up that frontend:
  neither API had CORS configured at all before this. Verified via a
  real CORS preflight request with `Origin: null` (what `file://` pages
  send) against a live server -- confirmed the right
  `Access-Control-Allow-*` headers come back.

**Also (`../frontend`):** replaced the Streamlit prototype with a
single-file HTML/JS chat UI that talks to this API and the ingestion
API directly -- no build step, no Python environment of its own. Each
sidebar "conversation" maps directly onto a `session_id`; attaching a
file routes to `/ingest` instead of `/query` and auto-calls `/reload`
afterward, closing the exact "forgot to reload" confusion hit while
testing the Streamlit version. See `../frontend/README.md`.

## [0.4.2] — 2026-07-26

Docs/environment only — no application code changed. `EmbeddingFactory`
and the reranker already auto-detected CUDA; the only gap was which
`torch` build happens to be installed.

**Added:**
- `docs/03-development-guide.md` — documents the optional local-GPU
  install (`torch==2.7.1+cu126`/`torchvision==0.22.1+cu126` from
  PyTorch's own index, matching the exact pinned versions), including a
  Windows-specific gotcha: `pip install` can fail with `Access is
  denied` on a `torch\_C...pyd` file if an IDE (VS Code/Pylance) has
  the venv open and is holding a lock on the installed package's binary
  files — took two failed install attempts to diagnose.
- `docs/reports/2026-07-26-performance-and-deployment-readiness.md` —
  real before/after: reranking dropped from ~700-725ms (CPU) to
  **~125-180ms** (GPU, GTX 1650/4GB), a genuine 4-5x speedup on the
  dominant cost in the retrieval path. Trade-off: embedding-model
  startup roughly doubled (~17s -> ~30s, one-time CUDA context init).

**Deliberately unchanged:** `requirements.txt` stays pinned to
CPU-only `torch` — installs cleanly everywhere (the `v0.4.0` CI, most
cloud deployment targets, machines without an NVIDIA GPU). This is a
local-dev-only opt-in, not a new default.

**Validated:** full test suite (83 tests) + the real 20-question
regression suite re-run on GPU: same pattern as the CPU baseline
(19/20 correct, the one gap reproducing the already-documented LLM
sampling variance from `v0.4.0`, not a new regression) — confirms the
hardware change affects speed only, not answer quality.

## [0.4.1] — 2026-07-26

Found via real multi-turn use through the new local frontend (first
real dogfooding of the chat flow end to end).

**Fixed:**
- `src/processing/query_rewriter.py` — the rewrite prompt told the LLM
  to "resolve pronouns using history" with no guidance on *which*
  referent to prefer when more than one topic had been discussed. Given
  history that covered a paper's improvements broadly, then specifically
  defined "spatial pyramid pooling" in the very next turn, "give me
  detailed intuition of it" resolved to "intuition of the proposed
  model" (the earlier, more-discussed topic) instead of "intuition of
  spatial pyramid pooling" (what was actually named last) — a wrong,
  repeated-earlier-answer, not a retrieval failure. Added an explicit
  recency-priority rule ("the last thing named beats the main topic of
  the conversation") plus a matching few-shot example. Reproduced
  against the real LLM with the exact failing conversation, before and
  after: 3/3 consistent correct resolution after the fix, existing
  examples (including the prompt's own "Deep Learning book" case)
  unaffected.

## [0.4.0] — 2026-07-26

Closes out the v0.4.0 "Multi-user & production hardening" milestone in
one batch, following the deployment-readiness report and the LLM-call
resilience fix (`v0.3.1`). Every item verified against the real
endpoints/service, not just unit tests with mocks.

**Added:**
- `src/utils/auth.py` — auth now fails closed: outside
  `APP_ENV=development` (the default), a missing `RAG_API_KEY` is a
  startup-time `RuntimeError`, not a warn-and-allow-everything no-op.
- `src/api.py` — per-client (IP) rate limiting via `slowapi`: `/query`
  at 10/minute. Defense in depth beyond the LLM-call throttling added
  in `v0.3.1` (different layer — protects the service itself from a
  single client, not just the shared Groq quota from all clients
  combined).
- `src/services/rag_service.py` — session store is now bounded
  (`MAX_SESSIONS=1000`, `RAG_MAX_SESSIONS` env override) with LRU
  eviction, instead of an unbounded dict that could grow indefinitely
  under public traffic with client-generated session IDs.
- `src/retrieval/vectorstore.py`, `src/services/rag_service.py` —
  `RAGService` now tolerates "no FAISS index yet" at startup (a fresh
  shared volume before any ingestion has run): stays up, `/health`
  still reports OK, `/query` answers clearly instead of crash-looping.
  Recovers automatically once `reload_index()` finds a real index.
- `.github/workflows/tests.yml` — CI runs the fast test suite (no
  credentials/model download needed) on every push/PR.

**Consumes (from the sibling `ingestion_fixed` `v0.4.0`):**
- Auto-reload: `/ingest` now notifies this API's `/reload` automatically
  after a successful ingestion, via `RAG_RELOAD_URL` in the shared
  `docker-compose.yml`. No more manual `/reload` call needed in that
  deployment path.

**Validated:** full test suite (83 tests, all passing) + the real
20-question regression suite (Factor Analysis + EfficientNet) re-run
after all of the above: 19/20 fully correct on the first pass, the one
gap (EfficientNet Q5) reproduced as already-documented LLM sampling
variance (confirmed via an immediate retry, correct) rather than a
regression -- 20/20 achievable, zero regressions from this batch.

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
