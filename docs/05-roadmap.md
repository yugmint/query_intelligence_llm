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
- [x] **Metadata-aware retrieval filtering — shipped and validated
      2026-07-27.** `/query` accepts an optional `source` field (API) /
      `metadata_filter` param (`RAGService.ask()`), threaded through
      `RAGState.metadata_filter` to `nodes/retrieve_context.py`: when
      present, retrieval calls `resources.vectorstore.similarity_search`
      directly (FAISS's own native metadata filter support) instead of
      the pre-built `resources.retriever`, which has no way to accept a
      per-query filter override (its `search_kwargs` are fixed at
      construction time). Unfiltered queries are unchanged — same
      retriever, same code path as before this existed. Added a new
      `GET /sources` endpoint (`RAGService.list_sources()`) so a caller
      can discover valid `source` values instead of guessing a filename;
      without it, source-filtering would be nearly unusable. Matters now
      that ingestion is additive (v0.4.0): one index can hold several
      unrelated documents, and until this, a query had no way to scope
      itself to just one of them.
      Verified against a real shared 2-document index (`faiss_index/`,
      "Grandma's Bag of Stories" + `Factor_Analysis.pdf`, ingested via
      the sibling `ingestion_fixed` pipeline): `list_sources()` correctly
      reports both (314 and 83 chunks); an unfiltered "grandmother"
      question correctly retrieves only from the Grandma document; the
      same question filtered to `Factor_Analysis.pdf` retrieves **zero**
      documents and the model answers "I don't know" — proving the
      filter genuinely excludes the other document's content rather
      than just re-ranking around it. 8 new unit tests (filter-branching
      in `retrieve_documents`, `ask()`'s filter threading,
      `list_sources()` aggregation/edge cases); full suite: 90/90
      passing, zero regressions.
- [x] **Chunk dedup / diversity at rerank — shipped and validated
      2026-07-27.** The cross-encoder scores each candidate
      independently and has no notion of redundancy against what it's
      already picked, so two near-identical chunks (e.g. from chunk
      overlap, or the same passage present twice after a re-ingestion)
      could both land in the reranked top-k, crowding out a genuinely
      distinct, lower-scoring chunk. `nodes/rerank.py`'s new
      `_select_diverse_top_k` greedily walks the score-descending
      ranking and skips any candidate whose text is >=80% similar
      (`difflib.SequenceMatcher` ratio, `CHUNK_DEDUP_SIMILARITY_THRESHOLD`
      in `src/retrieval/config.py`) to one already selected, letting the
      next-best distinct candidate fill that slot instead. Threshold
      calibrated against `ingestion_fixed`'s real chunk_overlap ratios
      (~15-22% of chunk_size across its document-type profiles) so
      normal chunk overlap isn't flagged — only near-total duplicates.
      Can return fewer than `TOP_K` documents if too few distinct
      candidates exist, same as the existing "fewer candidates than
      TOP_K" behavior, rather than padding with near-duplicates.
      11 new unit tests.
      **Validated against real data:** re-ran the full 26-question
      regression suite (Factor Analysis + EfficientNet + the airlock
      document) at the retrieve+rerank level — dedup never fired on any
      of the 26 real questions (no natural near-duplicates in these
      three documents' top candidate pools), confirming zero regressions
      on the existing suite. To confirm the feature actually works
      against the failure mode it targets (not just synthetic unit-test
      strings), re-ingested `Factor_Analysis.pdf` a second time into a
      scratch copy of its index — real duplicate ingestion, the
      documented `v0.4.0` incremental-ingestion behavior — and re-ran a
      real query: correctly skipped 2 literal-duplicate candidates,
      returning 3 distinct chunks instead of wasting slots on repeats.
- [x] **Source-attribution failure — fixed 2026-07-26.** The
      EfficientNet report's Q1 (confidently wrong answer, a References-
      section citation mistaken for the document's own title) went
      wrong → safe refusal (after reranking) → now **fully correct**:
      `ingestion_fixed` `v0.2.0` added `is_reference_section` per-chunk
      metadata; the `rerank` node (`src/workflow/nodes/rerank.py`) now
      drops those candidates before scoring, so a citation formatted
      like the document's own title can no longer out-rank the real
      thing. Re-running the EfficientNet Q1 question after re-ingesting
      with the new metadata: exact correct title, grounded in a running
      page-header repetition (page 5), not a citation. Full 10-question
      regression suites for both Factor Analysis and EfficientNet: 20/20
      correct (up from 16/20 fully-correct-or-safe before this fix —
      see `docs/reports/2026-07-24-reranking-validation.md` for the
      prior baseline). **Not fully general yet:** the airlock paper's
      equivalent question ("what is the title, who are the authors")
      still safely refuses rather than answering — that document's
      title/author chunk has its own, different problem (a chunk-
      boundary issue, investigated and reverted — see
      `ingestion_fixed/docs/05-roadmap.md` v0.2.0), unrelated to
      reference-section filtering. This fix closes the citation-
      mistaken-for-title failure mode specifically, not identity
      questions in general.
- [x] **Generation picks the wrong number when the reranked top-3
      doesn't contain the cleanest source sentence — dedicated numeric-
      question path shipped and validated 2026-07-27.** Found
      2026-07-25 testing a fourth real document (Hu et al. 2020, COVID-19
      severity study). Asked "what was the sample size?"; the model
      answered "120" instead of the correct "40". **Corrected diagnosis
      (2026-07-25, later same day):** originally logged as a generation
      reading-comprehension gap — traced the actual context and found
      the clean sentence (*"Results: A total of 40 patients were
      enrolled..."*) ranked #8/15 after reranking and never reached
      `TOP_K=3`; a prompt-only fix couldn't help since the model never
      saw the source text at all. **Deeper root cause found re-
      investigating 2026-07-27** (this diagnosis had actually understated
      it): the correct chunk isn't a near-miss at `RERANK_CANDIDATES=15`
      — pure FAISS bi-encoder similarity search ranks it **65th of 84**
      chunks in the document for this query, because the distractor
      sentence lexically repeats "sample size" three times while the
      correct sentence never uses that phrase. Even widening to nearly
      the full document (`k=70-84`) only brings the cross-encoder's rank
      to **#8** — confirming this needs real retrieval-ranking work, not
      a bigger `TOP_K`.
      **Shipped:** a dedicated numeric-question path
      (`src/processing/numeric_question.py::is_numeric_question` — a
      fast deterministic pattern match, no extra LLM call) that widens
      *only* numeric queries' candidate pool
      (`RERANK_CANDIDATES_NUMERIC=80`) and `TOP_K`
      (`TOP_K_NUMERIC=8`, see `src/retrieval/config.py`), reusing the
      same direct-vectorstore path this v0.2.0 metadata-filter feature
      already added to `nodes/retrieve_context.py`. Non-numeric queries
      (the large majority) are completely unaffected — same code path,
      same cost, as before this existed. Also strengthened the existing
      `src/prompts/generation.py` guideline to explicitly prefer a
      sentence that breaks its total down into consistent subgroups
      (a real signal of being the actual sample-size statement) over one
      naming a broader background population — this mattered because
      once the correct chunk actually reached context, the model still
      sometimes quoted the distractor's framing instead.
      **Validated against real data:** the exact originally-reported
      question ("what was the sample size in this study?") now answers
      correctly, verified 3/3 consistent runs. Full 26-question
      regression suite re-run (Factor Analysis 10 + EfficientNet 10 +
      this document's 6) in isolated processes per index: zero
      regressions, one additional real improvement (Factor Analysis'
      "how many variables" question, previously an honest "I don't
      know", now correctly answers "6"). **Known limitation, found
      during this validation:** the fix is phrasing-sensitive, not a
      full solve — a compound rephrasing of the same question ("what
      was the sample size *and study design*?") still gets the
      distractor's answer. Traced: the correct chunk does reach the
      widened 80-candidate pool (rank 53/84) but the cross-encoder still
      doesn't rank it in the numeric top-8 for that exact wording, since
      the distractor sentence also directly speaks to "study design"
      (a compound question genuinely has two different "most relevant"
      chunks). Not solvable by widening further without also solving
      the general reranking-quality problem — left open, documented
      here rather than silently shipped as if fully solved.
      Full trace: `docs/reports/2026-07-25-airlock-paper-e2e-test.md`.
- [x] **Query rewriter recency bug — fixed 2026-07-26.** Found via real
      multi-turn use through `../frontend`: the rewrite prompt said
      "resolve pronouns using history" with no guidance on *which*
      referent to prefer when more than one topic had come up. Given
      history that covered a paper's improvements broadly, then
      specifically defined "spatial pyramid pooling" in the very next
      turn, "give me detailed intuition of it" resolved to "intuition
      of the proposed model" (the earlier, more-discussed topic)
      instead of "intuition of spatial pyramid pooling" (what was
      actually named last) — a wrong, repeated-earlier-answer, not a
      retrieval failure. Added an explicit recency-priority rule plus a
      matching few-shot example to `src/processing/query_rewriter.py`.
      Reproduced against the real LLM with the exact failing
      conversation, before and after: 3/3 consistent correct resolution
      after the fix, existing examples unaffected.

(Query rewriting — `QueryRewriter` / `process_query` — already shipped,
landed in commit `5e12446`.)

## v0.3.0 — Advanced retrieval (README Phase 3)

- [x] **Hybrid search (BM25 + dense) — shipped and validated 2026-07-27.**
      FAISS's bi-encoder similarity search is a purely semantic match --
      it can under-rank a chunk containing an exact keyword/identifier
      (a model name, acronym, specific term) the query names literally,
      the flip side of the very failure mode the numeric-question
      recency-bias work (above) already found for lexical-vs-semantic
      mismatches. Added a sparse (BM25) retriever
      (`src/retrieval/bm25.py::BM25Factory`, via
      `langchain_community.retrievers.BM25Retriever` /
      `rank_bm25` -- new dependency) built from the same vectorstore
      corpus, fused with the existing dense retriever's candidates via
      Reciprocal Rank Fusion (`src/retrieval/hybrid.py`, standard
      RRF, `k=60`) before reranking. `RAGResources` gained a
      `bm25_retriever` field, rebuilt in lockstep with the vectorstore
      on every `reload_index()` call (`BM25Retriever` has no
      add-in-place API, so it's rebuilt from scratch each time --
      infrequent enough, and fast enough at this project's corpus
      sizes, that this is simple and sufficient).
      **Deliberately scoped to the plain path only** (no metadata
      filter, not a numeric question) -- BM25 doesn't support
      per-document filtering the way FAISS's own filter does, and the
      numeric-question widening already targets a semantic-recall gap
      that lexical matching wouldn't help with (that failure's
      distractor sentence lexically matches the query *better* than the
      correct chunk does -- BM25 would favor it even more, not less).
      15 new unit tests (RRF fusion arithmetic, node-level scoping
      guards confirming BM25 is never invoked on the filter/numeric
      paths).
      **Validated against real data:** confirmed hybrid fusion is
      genuinely active, not a no-op -- on the real Factor Analysis
      index, fusion changed the top-3 candidate ranking for 3/3 plain
      questions tested (e.g. "What is factor analysis?": dense alone
      surfaced a boilerplate software-header chunk first; fusion
      correctly promoted the actual definitional chunk instead). Full
      26-question regression suite (Factor Analysis + EfficientNet +
      the airlock document) re-run through the real `RAGService.ask()`
      end-to-end: zero regressions (one apparent difference on a
      re-run traced to pre-existing LLM sampling variance on a
      *numeric* question -- confirmed unrelated to this change, since
      hybrid search doesn't touch the numeric path at all).
- [x] **Parent-child retrieval — shipped and validated 2026-07-28.**
      Not built: a separate parent-document store (e.g. LangChain's
      `ParentDocumentRetriever`) -- ingestion already tags every PDF
      chunk with `page_number`/`source`, and the vectorstore already
      holds every chunk from that page, so "parent" is just "the rest
      of this page's chunks, looked up in the vectorstore's own
      docstore." No ingestion-side changes, no new storage.
      `src/retrieval/parent_context.py::expand_to_parent_context`:
      after rerank picks the small, precisely-matched chunks,
      generation's `context` is built from each chunk's full parent
      page instead of just the matched chunk -- `documents`/citations
      stay scoped to what actually matched. Wired into
      `nodes/rerank.py` in place of the raw chunk join.
      **Real bug found and fixed during validation, not just
      theorized:** expanding `TOP_K_NUMERIC=8` chunks to full dense
      pages hit a genuine Groq 413 ("Requested 7735" vs the 6000 TPM
      hard ceiling) on a real query. Added
      `PARENT_CONTEXT_MAX_CHARS_PER_PAGE` (1500, `src/retrieval/config.py`):
      a page over budget falls back to just the matched chunk rather
      than an arbitrary truncated slice, since the matched chunk could
      sit anywhere in an oversized page and blind truncation risks
      cutting out the very thing that was relevant.
      Context compression (the other half of this roadmap line) not
      attempted -- parent expansion is the opposite direction (more
      context, not less); no evidence yet that context length itself
      (as opposed to per-request size, which the cap above already
      addresses) is a real problem worth solving.
      10 new unit tests. **Validated against real data:** confirmed
      expansion is genuinely active (1,495 → 7,203 chars on a real
      query); full 26-question regression suite re-run end-to-end
      after the fix -- zero regressions, the previously-hedging
      "how many variables" answer is now clean, no more 413s anywhere
      including the numeric-widened path that originally triggered one.

## v0.4.0 — Multi-user & production hardening

- [x] **LLM-call resilience — fixed 2026-07-26.** Found via a real test,
      not a hypothetical: 5 concurrent requests crashed Groq's free tier
      (6,000 TPM for `llama-3.1-8b-instant`) with an unhandled
      `RateLimitError` on request 2 — see
      `docs/reports/2026-07-26-performance-and-deployment-readiness.md`
      §2. Considered switching providers first (Cerebras: blocked on
      account billing status, and its free tier is being retired
      2026-08-17 regardless; Google Gemini: free-tier traffic may be used
      to improve Google's products, ruled unacceptable for a public
      service) — confirmed Groq already has a strict no-training policy
      (SOC 2 Type II), so hardening the existing provider was both the
      simplest and most privacy-safe fix, not a compromise. `LLMFactory`
      (`src/retrieval/llm.py`) now attaches a client-side
      `InMemoryRateLimiter` (tuned to stay under the 6,000 TPM ceiling
      with margin) plus `max_retries=3` and a 30s timeout; `src/api.py`'s
      `/query` handler catches any exception that still gets through and
      returns a clean 503 instead of an unhandled 500. Re-ran the exact
      failing scenario: no crash, requests queue and complete instead.
      Honest remaining limit: this doesn't raise the $0-budget ceiling,
      it just fails gracefully instead of hard — sustained heavy traffic
      still means real queuing delay.
- [x] **Bounded session memory — fixed 2026-07-26.** `RAGService._sessions`
      was a plain dict, one entry per distinct `session_id`, never
      evicted -- public traffic with client-generated session IDs could
      grow it indefinitely (trivial to trigger: send N distinct IDs).
      Replaced with an `OrderedDict` + LRU eviction (`MAX_SESSIONS=1000`
      default, `RAG_MAX_SESSIONS` env override) -- the least-recently-used
      session is dropped once full, so an active conversation is never
      evicted out from under it. `reset_memory` routed through the same
      bounded-insert path so it can't bypass the cap. Not persistent
      across restarts (still in-process) -- that would need a shared
      backend (Redis) and wasn't needed at current scale. 6 new tests.
- [x] **Rate limiting on the API — fixed 2026-07-26.** Per-client (IP)
      limits via `slowapi` (in-memory backend, no Redis needed at this
      scale): `/query` at 10/minute, `/ingest` at 5/minute (stricter --
      each call is ~3s of real CPU-bound embedding work, not just an LLM
      call). Defense in depth beyond the LLM-call throttling above --
      that protects the shared Groq quota from the *aggregate* of all
      clients; this protects the service itself from any *single*
      client hammering it with requests that never even reach the LLM.
      Verified against the real endpoints: exact request counts allowed
      through, clean 429s after.
- [x] **Auto-reload after ingest — fixed 2026-07-26.** `ingestion_fixed`'s
      `/ingest` now POSTs to this API's `/reload` automatically after a
      successful ingestion, via `RAG_RELOAD_URL` (opt-in — unset means
      the old manual-call behavior, unchanged). Best-effort: a failed
      notification logs a warning and does *not* fail the `/ingest`
      call, since the FAISS write already succeeded by then. Verified
      against a real running server, including the auth-failure path
      (wrong key -> clean "failed: 401..." status, not a crash). Wired
      into the shared `docker-compose.yml`.
- [x] **`RAGService` tolerates "no index yet" — fixed 2026-07-26.**
      `VectorStoreFactory.load` now returns `None` (checking for
      `index.faiss` explicitly, not catching-and-guessing from FAISS's
      generic `RuntimeError`) instead of raising when no index exists
      yet at the configured path. `build_resources()`/`RAGService.ask()`
      handle `retriever=None` by answering "I don't have any documents
      loaded yet" instead of crashing -- the service stays up, `/health`
      still reports OK, and `reload_index()` recovers cleanly once a
      real index exists. Verified end-to-end (missing index -> graceful
      answer -> reload -> real answer, no restart needed). This was the
      exact rough edge `docker-compose.yml` documented as unresolved.
- [x] **Auth fail-closed — fixed 2026-07-26.** Outside `APP_ENV=development`
      (the default, preserving today's no-env-vars-needed local workflow),
      a missing `RAG_API_KEY`/`INGESTION_API_KEY` is now a startup-time
      `RuntimeError`, not a warn-and-allow-everything no-op -- a single
      missing env var in deployment config can no longer silently give
      public unauthenticated access. Applied identically to both APIs.
- [x] **CORS middleware — fixed 2026-07-26.** Neither API had any CORS
      configuration at all -- browsers silently block every request
      from any frontend not served from the exact same origin,
      including a `file://`-opened local HTML page (exactly how
      `../frontend/index.html` runs). Found while wiring that frontend
      up. `CORSMiddleware` added, wide open by default
      (`CORS_ALLOW_ORIGINS` env override for a real deployment that
      wants to restrict it) -- API-key auth is the actual
      access-control layer once `APP_ENV` is outside `development`,
      CORS alone was never meant to be that. Verified via a real
      preflight request with `Origin: null` (what `file://` pages send)
      against a live server.

## Local tooling (outside the 5-phase framing)

Developer-experience additions that don't fit "Production RAG Workflow →
Intelligence Layer → Advanced Retrieval → Enterprise Features → Agentic
Intelligence" as customer-facing phases, but are real, shipped work.

- [x] **`../frontend` — a local chat UI, added 2026-07-26.** Single-file
      HTML/JS, no build step, no Python environment of its own -- talks
      directly to this API and the ingestion API. Replaced an earlier
      Streamlit prototype once this held up in testing. Each sidebar
      conversation maps onto a real `session_id`; attaching a file
      routes to `/ingest` and auto-calls `/reload` afterward instead of
      requiring a manual step. Verified with a real Playwright-driven
      Chromium run against both live backends (ingest → auto-reload →
      grounded query → settings → theming → multi-conversation), zero
      console errors, zero failed requests. See `../frontend/README.md`.
- [x] **Optional local GPU acceleration — documented 2026-07-26.** No
      application code changed -- `EmbeddingFactory` and the reranker
      already auto-detected CUDA; the gap was only which `torch` build
      happens to be installed. `requirements.txt` stays pinned to
      CPU-only deliberately (installs cleanly in the CI above and most
      cloud deployment targets without a GPU) -- this is a documented
      local opt-in only. Measured effect (GTX 1650, 4GB): reranking
      dropped from ~700-725ms to ~125-180ms, a real 4-5x speedup. See
      `docs/03-development-guide.md`.

## v0.5.0 — Enterprise features (README Phase 4)

- [x] **Source citations in generated answers — shipped and validated
      2026-07-27.** `/query` now returns a `citations` field: one entry
      per distinct `(source, page)` pair among the chunks actually
      handed to generation, in relevance order
      (`src/services/citations.py::build_citations`, derived from
      `RAGState["documents"]` after retrieval → dedup → rerank —
      computed in `RAGService.ask()`, not a graph node, since it's a
      response-shaping concern over the final state rather than
      something any node reads or writes mid-workflow). `page` comes
      from `ingestion_fixed`'s `PDFLoader`, which already tags every
      page-level `Document` with `page_number` before chunking (and
      that metadata already survives chunking — confirmed via
      `RecursiveChunker`'s `{**document.metadata}` spread); `None` for
      sources without page-level metadata.
      **Deliberately chunk-provenance, not verified per-claim
      attribution:** lists what was provided as context, not a proof the
      model drew on every listed source in its final wording. Considered
      asking the model to self-report which chunks it used (e.g. inline
      `[1]`/`[2]` markers), but `generate_knowledge.py` already has an
      unused structured-JSON-response attempt that silently fails on
      nearly every real call (logged as "Structured JSON response not
      received") — inheriting that same unreliability for citations
      would make them look more precise than they'd actually be.
      Chunk-provenance is the honest, verifiable thing to offer instead.
      New `Citation` pydantic model in `src/api.py`
      (`{source: str, page: int | None}`); the no-index short-circuit
      path and conversation-intent answers both correctly return `[]`.
      `../frontend/index.html` renders it as a `sources:` line alongside
      the existing `intent:` badge.
      15 new unit tests. **Validated against real data:** a real query
      against the live API (`curl -X POST /query`) returned
      `"citations":[{"source":"Factor_Analysis.pdf","page":3},
      {"source":"Factor_Analysis.pdf","page":12}]` for "Who documented
      the scree graph?" — correct, matches the actual source pages.
      Also verified on the `v0.5.0` metadata-filter path (source-scoped
      query against the shared 2-document index correctly cited only
      the filtered document). Playwright screenshot confirms the
      frontend renders it correctly end-to-end.
- [x] **Streaming responses — shipped and validated 2026-07-27.** New
      `POST /query/stream` (Server-Sent Events, `data: <json>\n\n`
      frames) alongside the existing `/query`, which is untouched.
      `RAGService.ask_stream()` reuses the exact same compiled graph as
      `ask()` -- just consumed via LangGraph's own
      `stream_mode=["messages", "values"]` instead of `.invoke()`,
      confirmed empirically to work with this project's pinned
      `langgraph==0.2.76` + `ChatGroq` before committing to the design.
      `"messages"` streams token-by-token from *every* LLM call in the
      graph, not just the final answer -- filtered to only forward
      `generate`/`conversation` node output (`_STREAMED_NODES`), so
      `detect_intent`'s raw classification JSON never leaks to the
      client. The final `"values"` payload (LangGraph's complete final
      state, after the `memory` node has run) is used to build the same
      `citations`/`intent`/`status` `/query` already returns, sent once
      as a closing `{"type": "done", ...}` event.
      **Real, necessary fix found along the way:**
      `nodes/generate_conversation.py` asked the model to wrap its
      reply in `{"response": "..."}` JSON -- streaming that raw would
      show the user a literal `{`, `"response": "`, etc. typing itself
      out instead of clean text. Rewrote it to ask for plain text
      instead, matching `generate_knowledge.py`'s prompt (which already
      demonstrated the JSON-wrapper instruction wasn't reliably honored
      anyway -- it logs "Structured JSON response not received" on
      nearly every real call). Mid-stream failures (LLM error after
      retries exhausted) can't use `/query`'s clean-503 pattern -- the
      response's 200 status is already committed once streaming starts
      -- so they're signaled in-band as a `{"type": "error", ...}`
      event instead.
      `../frontend/index.html` rewritten to consume the stream via
      `fetch()` + a manual `ReadableStream` reader (native `EventSource`
      is GET-only and can't carry the JSON body `/query/stream` needs) --
      the assistant's message now grows incrementally in the UI rather
      than appearing all at once.
      13 new/rewritten unit tests (`ask_stream()`'s node-filtering and
      final-event assembly; `generate_conversation`'s plain-text
      behavior).
      **Validated against real data:** confirmed real token-by-token
      SSE delivery via a timestamped `requests` client against a live
      server (not just checking the response shape). Groq's inference
      is fast enough that a full ~80-token answer streamed in ~1
      second end-to-end -- streaming's main real benefit here is a
      faster perceived response and not blocking on the whole answer,
      more than a dramatic visible typing effect. Playwright: sampled
      the assistant message's rendered length every 150ms during a real
      request and confirmed genuine incremental growth (0 → 78 → 466
      chars), not a single final paint; screenshot confirms correct
      final rendering with citations/intent intact.
- [x] **Observability / metrics dashboard — shipped and validated
      2026-07-27.** New `GET /metrics` (Prometheus text-exposition
      format), auth-protected like every other non-`/health` endpoint
      -- these numbers reveal real traffic patterns, not something to
      expose unauthenticated on a public deployment.
      Scope, chosen with the user upfront rather than assumed: real
      Prometheus/Grafana support *plus* a built-in dashboard page, so
      this is useful with zero extra infrastructure and still plugs
      into real monitoring tooling if you have it.
      `src/utils/metrics.py` defines a small, fixed metric set rather
      than instrumenting everything: `rag_node_duration_seconds`
      (Histogram, per-node latency) and `rag_node_failures_total`
      (Counter) hook into `src/utils/decorators.py::log_node` -- the
      single decorator every one of the 8 LangGraph nodes already goes
      through, so this instruments all of them without touching each
      node file individually. `rag_requests_total` (Counter, by
      endpoint + outcome) covers `/query` and `/query/stream`.
      `rag_active_sessions` (Gauge) is set at scrape time from the new
      `RAGService.active_session_count()`.
      `../frontend/dashboard.html` — a second buildless static page
      (same visual system as `index.html`, own settings drawer/API key,
      own localStorage key) that polls `/metrics`, parses the
      Prometheus text format client-side (a ~20-line parser, not a
      dependency), and renders stat cards + a per-node latency table +
      a requests-by-outcome table, auto-refreshing on a configurable
      interval.
      18 new unit tests (metrics recording via the decorator hook,
      `active_session_count()`).
      **Validated against real data:** started a live server, sent real
      traffic (`/query`, `/query/stream`, including a session with no
      real answer), and confirmed `GET /metrics`'s raw output correctly
      reflected it -- exact request/session counts, real per-node
      latency numbers matching this session's own previously-observed
      Groq latency patterns (Intent ~9.7s avg, Generate_Knowledge
      ~10.8s avg), zero node failures recorded on a clean run.
      Playwright: loaded `dashboard.html` against that same live
      server and confirmed every card/table value matched the raw
      `/metrics` output exactly; screenshots confirm correct rendering
      in both dark and light theme.
- [x] **Expanded guardrails — shipped 2026-07-27.** Added
      `SensitiveInfoValidator` (email/SSN/phone/API-key regex + a Luhn
      check for card numbers, to avoid false-positiving on any 13-16
      digit string) and `ToxicityValidator` (blocked-word list), same
      chain-of-responsibility shape as the existing 5 validators. 12
      new tests.
      Scoped down, not built as listed: **language detection and role
      validation skipped** -- no stated need to restrict languages, and
      there's no role/RBAC model anywhere in this codebase for "role
      validation" to validate against (API-key auth is binary
      allow/deny). Speculative infra for a system that doesn't have it;
      add if a real multi-role auth model ever lands.
      Toxicity detection is a wordlist, not a real classifier --
      misses coded/implicit toxicity, marked with a `ponytail:` comment
      naming the ceiling (upgrade: Perspective API / a small local
      model) rather than pulling in a new ML dependency for it.

## Unscheduled

- [x] **CI (GitHub Actions) — added 2026-07-26.**
      `.github/workflows/tests.yml` runs `pytest tests/ -v` on every
      push/PR. No credentials needed -- the fast suite uses fakes for
      the LLM/retriever/reranker, verified locally with all relevant
      env vars cleared before adding the workflow.
- [ ] Agentic Intelligence (README Phase 5) — multi-agent, tool calling,
      web search. Deliberately not scheduled into a version yet; too far
      out to commit to a shape.
