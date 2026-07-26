# Performance Report — Ingestion & Retrieval Layers, Public-Deployment Readiness

**Date:** 2026-07-26
**Versions:** `ingestion_fixed` `v0.2.0`, `RAG_Project_1` `v0.3.0`
**Method:** every number below is real, measured output from this session, not
estimated. CPU-only (no GPU used anywhere in this stack). Embedding model:
`all-MiniLM-L6-v2`. Reranker: `cross-encoder/ms-marco-MiniLM-L-6-v2`. LLM:
Groq `llama-3.1-8b-instant` (external API, `on_demand`/free tier).

**Bottom line up front: not ready for public deployment as-is.** Accuracy is
genuinely strong. The blocker isn't correctness — it's that the system falls
over under trivially light concurrent load, for a reason that has nothing to
do with either layer's own code. Details and a fix-before-shipping checklist
below.

---

## 1. Ingestion layer performance

### Speed

Measured with the embedding model already warm (i.e. steady-state, not
cold-start) — ingesting three real documents back to back in one process:

| Document | Pages | Chunks | Time | Per-page |
|---|---|---|---|---|
| Factor_Analysis.pdf | 16 | 83 | 3.39s | 212ms |
| Computer Vision_2.pdf (EfficientNet) | 11 | 79 | 3.28s | 298ms |
| airlock-...27.pdf (Hu et al.) | 12 | 84 | 3.24s | 270ms |

Stage breakdown (EfficientNet paper, representative):

| Stage | Time | Notes |
|---|---|---|
| Embedding model load | 17.5s | **One-time**, at service startup only |
| PDF load (`pypdf`) | 0.74s | Scales with page count/complexity |
| Clean + analyze + chunk + metadata | <10ms combined | Negligible |
| Embed + FAISS index build | 2.67s | **Dominant cost**, ~34ms/chunk |

Ingestion time is driven almost entirely by embedding, which scales with
chunk count, not page count — the near-identical totals above despite
16 vs. 11 pages is because chunk counts landed close together (79-84).
Rough rule of thumb on this hardware: **~35ms per chunk**, plus PDF-load
overhead. A 100-page paper producing ~500 chunks would take roughly
17-20s to ingest, steady-state.

The 17.5s model-load cost is paid once per process lifetime (both
`IngestionPipeline` and the FastAPI service build it once at startup,
confirmed in code) — not a per-request cost, but it is real cold-start
latency the first deploy (or every restart) has to absorb.

### Accuracy

Classification and chunking accuracy, validated across four structurally
different real documents this session and last:

| Document | Type | Classification | Confidence |
|---|---|---|---|
| Grandma's Bag of Stories (narrative) | book | `book` ✅ | — |
| Factor_Analysis.pdf (technical/reference) | — | `general` ✅ (was `book`, fixed) | 0.60 |
| Computer Vision_2.pdf (EfficientNet) | research paper | `research_paper` ✅ | 0.90 |
| airlock-...27.pdf (Hu et al., structured abstract) | research paper | `research_paper` ✅ (was `legal`, fixed) | 0.90 |

Every misclassification found via real-document testing this session has
been fixed and regression-tested (`v0.1.2`, `v0.1.3`). No known
misclassification bugs remain open. `average_paragraph_length`
unreliability remains open but is cosmetic (doesn't affect the actual
chunking decision in any case observed so far).

### Resource footprint

- Embedding model (`all-MiniLM-L6-v2`): ~90MB on disk, ~400MB resident once loaded (typical for this model class).
- Reranker (`ms-marco-MiniLM-L-6-v2`): similar weight class, loaded separately by the RAG service, not the ingestion service.
- No GPU used or required at current volume; CPU inference throughout.
- FAISS index size: ~80 chunks/document at 384-dim float32 vectors ≈ negligible (well under 1MB per document indexed).

---

## 2. Retrieval layer performance

### Latency (sequential, single request)

| Query type | Time |
|---|---|
| Chit-chat/greeting (bypasses retrieval) | ~0.3s |
| Knowledge query (full pipeline) | ~0.9-1.1s |

Breakdown of the knowledge-query path (from earlier measurement,
`scripts/measure_reranking_latency.py`, still valid — chunking/metadata
changes since then don't touch this):

| Stage | Time |
|---|---|
| FAISS similarity search (k=15) | ~10-15ms |
| Cross-encoder rerank (15→3) | ~700-725ms |
| 2x Groq LLM calls (intent + generation) | remainder (~250-350ms combined — Groq is fast) |

Reranking, not the LLM, is the dominant cost. This matches the earlier
validation report's finding, now reconfirmed end-to-end.

### Accuracy

Full 10-question regression suites, re-run today after the section-role
metadata fix:

| Suite | Result |
|---|---|
| Factor Analysis | **10/10 correct** |
| EfficientNet | **10/10 correct** |
| airlock paper (Hu et al., partial suite) | 4/6 correct, 2 known/documented gaps (title-retrieval safe-refusal, one distractor-number miss) |

20/20 on the two fully-validated suites is a strong result — up from
16/20 before this session's fixes, with zero regressions confirmed via
re-running both suites after every change.

### Concurrency — the actual blocker

Ran 5 requests sequentially (4.86s total, ~1s each, as expected), then
the same 5 requests concurrently (5 threads). **The concurrent run
crashed on request 2 and 3** with:

```
groq.RateLimitError: Error code: 429 - Rate limit reached for model
`llama-3.1-8b-instant` ... on tokens per minute (TPM): Limit 6000,
Used 5902, Requested 931. Please try again in 8.33s.
```

This is not a bug in either repo's code — it's Groq's free/`on_demand`
tier TPM (tokens-per-minute) limit. Each knowledge query makes **two**
LLM calls (intent classification + generation) at roughly 900-1100
tokens each **per call** (prompt + context + response), so a single
knowledge query can burn ~1800-2200 tokens. Against a 6000 TPM ceiling,
that's a sustainable throughput of **roughly 3 knowledge queries per
minute** before requests start failing — and they fail **hard**: the
exception is unhandled anywhere in the stack (no retry, no backoff, no
queuing), propagates straight up through the LangGraph workflow, and
the API layer (`src/api.py`) has no try/except around `rag.ask()` at
all, so it surfaces as an unstructured 500 to the caller.

**This alone rules out public deployment on the current Groq tier.**
Any real public traffic — even a handful of simultaneous users, not an
attack — will hit this within seconds.

**Update (2026-07-26, later same day) — fixed.** Considered switching
providers for more headroom first: Cerebras (blocked — the account's
free tier requires a Personal-org API key and this account's key was
Team-org, returning `402 Payment required` on every model; also,
Cerebras's free tier is being retired 2026-08-17 in favor of a
credit-card-required model, a bad long-term bet regardless) and Google
Gemini (free tier may use prompt/response traffic to improve Google's
products — unacceptable for a public-facing service). Confirmed Groq
itself already has a strict no-training policy (SOC 2 Type II; not
permitted to use inputs/outputs for training without opt-in per their
Trust Center), making it the most privacy-safe option of the three
evaluated, not just the path of least resistance — so the fix was to
harden Groq itself rather than switch: `LLMFactory`
(`src/retrieval/llm.py`) now attaches an `InMemoryRateLimiter`
(`requests_per_second=0.08`, `max_bucket_size=2` — sustained rate stays
under the 6,000 TPM ceiling with margin, while letting one query's own
2 calls through together) plus `max_retries=3` and a 30s
`request_timeout` to the shared `ChatGroq` instance. Re-ran the exact
same 5-concurrent-request test: **no crash** (previously: crashed on
request 2). Requests now queue and complete successfully instead of
failing — confirmed via real output, staggered completion times
(50s/75s/100s/125s/138s for 5 concurrent requests) instead of a 429.
`src/api.py`'s `/query` handler also now catches any exception that
still reaches it (an exhausted retry budget, or an unrelated bug) and
returns a clean 503 instead of an unhandled 500.

**Remaining honest tradeoff:** this doesn't raise the underlying
ceiling — it makes hitting it degrade gracefully (queued delay) instead
of failing hard (crash). Sustained heavy public traffic will still mean
real wait times (tens of seconds to minutes under sustained
concurrent load) at this token budget. That's a genuine capacity limit
of the $0 constraint, not something client-side throttling can remove;
raising it for real means a paid tier or a different LLM strategy later.

---

## 3. Production-readiness gaps (beyond the rate limit)

Found by reading the actual deployment-facing code (`src/api.py`,
`src/utils/auth.py`, `src/ingestion/api.py`), not assumed:

| Gap | Where | Severity |
|---|---|---|
| **API key auth silently no-ops if `RAG_API_KEY`/`INGESTION_API_KEY` isn't set** — both APIs become fully unauthenticated with no error, just a startup log warning. A missed env var in deployment config = public-write access to both services. | `src/utils/auth.py` | High |
| **No rate limiting** on either `/query` or `/ingest` — confirmed absent, not just undocumented. Anyone with (or without, per above) the API key can send unlimited requests. | both APIs | High |
| ~~No retry/backoff on LLM calls~~ **Fixed 2026-07-26** — `LLMFactory` now attaches a client-side rate limiter + `max_retries=3` + 30s timeout; `/query` catches unhandled exceptions and returns a clean 503. | `src/retrieval/llm.py`, `src/api.py` | ~~High~~ Resolved |
| **Unbounded in-memory session store** — `RAGService._sessions` is a plain dict, one entry per distinct `session_id`, never evicted, lost on restart. Public traffic with client-generated session IDs grows this indefinitely — a slow memory leak, and a trivial one to trigger (send N different session_ids). Already documented as a known limitation, not previously flagged as a *public-facing* risk specifically. | `src/services/rag_service.py` | Medium-High |
| **No concurrent-write protection on the shared FAISS index** — `FAISSIndexer.save()` does a plain directory write, no locking, no atomicity. Two simultaneous `/ingest` calls, or an `/ingest` racing a `/reload`, can corrupt the index the query service reads from. | `ingestion_fixed/src/ingestion/indexers/faiss_indexer.py` | Medium (low likelihood at low traffic, high impact if it happens) |
| **No file-upload hardening on `/ingest`** beyond a size cap and extension check — no malware/content scanning, no rate limiting on upload frequency. | `ingestion_fixed/src/ingestion/api.py` | Medium |
| **No CORS configuration** — fine for server-to-server or same-origin use; will silently fail for any browser-based frontend calling this directly from a different origin. | `src/api.py` | Low (depends on deployment shape) |
| **No monitoring/alerting** — structured logs exist (good), but nothing watches them. A production incident (like the rate-limit crash above) would be silent until a user reports it. | both services | Medium |

---

## 4. Verdict

**Correctness: yes, genuinely strong.** 20/20 on two independently-validated
real-document suites, four different document types correctly classified,
zero open correctness regressions. This is the part of the system that's
actually ready.

**Operationally: closer, not there yet.** The rate-limit crash (§2) is
fixed — it degrades gracefully now instead of failing hard. That was the
most urgent gap because it turned *ordinary* light usage into failures,
not just abuse. What's left in §3 is real but lower-severity: a config
mistake (missing API key) is silently catastrophic rather than loud, and
there's no rate limiting or monitoring layer yet.

**Before shipping to the public, in priority order:**
1. ~~Upgrade off Groq's free tier / add throttling~~ **Done** — see the
   §2 update above. Sustained heavy traffic still means real queuing
   delay, not instant responses; that's the honest remaining tradeoff
   of a $0 budget, not a bug.
2. ~~Add retry-with-backoff and clean error responses~~ **Done** —
   same fix as #1.
3. Make auth **fail closed**, not open: refuse to start (or log a
   fatal error) if `RAG_API_KEY`/`INGESTION_API_KEY` is unset in a
   non-dev environment, instead of silently allowing everything.
4. Add basic rate limiting at the API layer (even a simple per-IP or
   per-key limiter) as defense in depth beyond #1.
5. Bound the session store (max sessions, or TTL-based eviction).

Items 2-5 are each small, contained changes — a day or two of focused
work, not a redesign. Item 1 is a decision (pay for a higher Groq tier
vs. self-host/swap the LLM), not an engineering task, and blocks
everything else in practice: no amount of retry logic fixes a hard
capacity ceiling of ~3 queries/minute.
