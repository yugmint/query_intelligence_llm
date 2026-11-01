# query_intelligence_llm ("Intelligent Document AI") — Technical Documentation

> Companion reference to [`README.md`](README.md) (feature list, roadmap, quick
> start). This document covers **actual architecture, module reference, data
> flow, and — critically — the history of the ingestion pipeline**, since
> multiple versions of it have existed inside this repo and it is no longer
> the same code path that builds the vector index this app reads from. If
> you're trying to understand "how does a document get from a PDF into an
> answer," read §8 first.

Repo remote: `github.com/yugmint/query_intelligence_llm`

---

## 1. What this project is

A LangGraph-orchestrated RAG chatbot: guardrails → intent detection → (query
rewrite →) retrieval → generation → memory. It is the retrieval/generation
half of a system whose ingestion half now lives in the separate
[`smart-document-ingestion-engine`](https://github.com/yugmint/smart-document-ingestion-engine/blob/main/DOCUMENTATION.md) project (see §8).
Its local folder is `ingestion_fixed`, and this repo's is `RAG_Project_1`;
the commands and project history below use those names.

An older, pre-LangGraph incarnation of this same project once had its README
preserved at `local/project_history/README_v3.md` — since deleted (an
untracked, gitignored local file, permanently lost in a cleanup pass on
2026-07-24; not recoverable). Per a reading of it earlier in that session,
it described a simpler LangChain-only pipeline: LLM-based intent
classification (greeting/chit-chat/knowledge), conversational memory, no
graph orchestration yet. That's a paraphrase from memory, not a verbatim
record — treat it as approximate. The current architecture (this document)
fully supersedes whatever it said either way.

Per the current `README.md`, the project positions itself as going beyond
plain RAG by adding an "intelligent workflow layer" (intent understanding,
input validation, conversation routing) on top of retrieval, with a 5-phase
roadmap: Phase 1 Production RAG Workflow (done), Phase 2 Intelligence Layer
(query rewriting — partially landed, see §5; reranking — not yet), Phase 3
Advanced Retrieval, Phase 4 Enterprise Features, Phase 5 Agentic Intelligence.

---

## 2. Entry point

`main.py` is a minimal REPL:

```python
from src.services.rag_service import RAGService
rag = RAGService()
while True:
    query = input("\nYou: ")
    if query.lower() == "exit":
        break
    answer = rag.ask(query)
    print(f"\nAssistant: {answer}")
```

`RAGService()` builds shared resources and compiles the LangGraph workflow
**once**; each loop iteration just invokes it. Run with:

```bash
python main.py
```

---

## 3. Architecture — `src/workflow/`

### 3.1 State — `state.py`

`RAGState` (TypedDict), the shape threaded through every node: `query`,
`rewritten_query`, `is_valid`, `guardrail_reason`, `intent`, `documents`,
`context`, `chat_history`, `session_id`, `session_memory`, `answer`,
`retry_count`, `status`, `metadata`.

> **Fixed 2026-07-24:** this used to declare `retrieved_documents` /
> `reranked_documents`, but `retrieve_context.py` actually wrote to a
> `documents` key instead — the `TypedDict` didn't describe what was
> actually in state at runtime. Renamed the declared field to `documents`
> to match reality; `reranked_documents` will come back once reranking
> (roadmap v0.2.0) is actually implemented, rather than being declared
> speculatively ahead of it.

### 3.2 Resources — `resources.py`

`RAGResources` is a **mutable** `@dataclass(slots=True)` (not frozen —
that's load-bearing, see below) acting as a dependency-injection
container: `llm`, `embeddings`, `vectorstore`, `retriever`, `reranker`.
**Not `memory`** — that's session-scoped and carried through
`RAGState["session_memory"]` per request instead (see §12), since a
process-wide `resources.memory` would race under concurrent requests for
different sessions. `build_resources()` (no arguments) builds each once
via factories:

```
EmbeddingFactory.get() → VectorStoreFactory.load(embeddings)
                       → RetrieverFactory.build(vectorstore)
RerankerFactory.get()
LLMFactory.get()
```

Called a single time in `RAGService.__init__`, then closed over by every node
function in `workflow.py` — this is what avoids reloading the embedding
model / FAISS index / LLM client / reranker on every request. Being
mutable (not frozen) is what lets `RAGService.reload_index()` swap
`resources.vectorstore`/`resources.retriever` in place without rebuilding
the compiled graph — see §12.

### 3.3 Graph — `workflow.py`

`build_workflow(resources)` builds a `langgraph.graph.StateGraph(RAGState)`:

```
START
  │
  ▼
input_guardrail ──(reject)──► guardrail_response ──► END
  │
 (continue)
  ▼
intent ──(conversation)──► conversation ──► memory ──► END
  │
 (knowledge)
  ▼
process_query ──► retrieve ──► generate ──► memory ──► END
```

Nodes (`src/workflow/nodes/`), each wrapped with `@log_node(...)` from
`src/utils/decorators.py` (times execution, logs start/completion/failure):

| Node | File | Responsibility |
|---|---|---|
| `input_guardrail` | `input_guardrail.py` | Runs `InputGuardrail().validate(state)` |
| `guardrail_response` | `guardrail_response.py` | Builds the rejection answer from `state["guardrail_reason"]`, sets `status="rejected"` |
| `intent` | `intent.py` | LLM classification → `greeting` / `chit_chat` / `knowledge`; falls back to `"knowledge"` on JSON-parse failure |
| `process_query` | `process_query.py` | Knowledge branch only. `QueryRewriter.get(resources).rewrite(...)` → `rewritten_query` |
| `retrieve` | `retrieve_context.py` | `resources.retriever.invoke(rewritten_query or query)` — pulls `RERANK_CANDIDATES` (15) chunks, not the final count |
| `rerank` | `rerank.py` | Cross-encoder scores the 15 candidates, keeps top `TOP_K` (3), rebuilds `context`. Added 2026-07-24 — see `docs/07-design-decisions.md` and `docs/reports/2026-07-24-reranking-validation.md`. |
| `generate` (knowledge) | `generate_knowledge.py` | Builds prompt via `src/prompts/generation.py`, invokes LLM, expects `{"response": "..."}` |
| `conversation` | `generate_conversation.py` | Inline prompt (not in `src/prompts/`) for greeting/chit-chat, no retrieval |
| `memory` | `update_memory.py` | Appends user/AI turn to `resources.memory` |

---

## 4. Architecture — `src/retrieval/`

This package is **retrieval-only** — it loads a pre-built FAISS index; it does
not build one. See §8 for where index-building logic used to live and where
it lives now.

| Module | Contents |
|---|---|
| `config.py` | Constants: `MODEL_NAME = "llama-3.1-8b-instant"`, `EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"`, `FAISS_PATH = "faiss_index"`, `TOP_K = 3` (final chunk count reaching generation), `RERANK_CANDIDATES = 15` (FAISS pull size before reranking), `RERANK_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"`. Also a leftover unused `pdf_path` constant, a vestige of the pre-refactor single-script era. |
| `embeddings.py` | `EmbeddingFactory` (singleton). Builds `HuggingFaceEmbeddings`, auto-selects `cuda` if `torch.cuda.is_available()` else `cpu`, `normalize_embeddings=True`. |
| `llm.py` | `LLMFactory` (singleton). Loads the Groq API key from `cred.json` (`grok_api_key`, or env `GROQ_API_KEY`), builds via `init_chat_model(MODEL_NAME, model_provider="groq")`. |
| `memory.py` | `get_memory()` → fresh `InMemoryChatMessageHistory` (non-persistent, per-process only — history is lost on restart). |
| `reranker.py` | `RerankerFactory` (singleton, lazy-imports `sentence_transformers.CrossEncoder` so importing this module doesn't force the import/download for callers that never rerank). Added 2026-07-24. |
| `retriever.py` | `RetrieverFactory.build(vectorstore)` → `vectorstore.as_retriever(search_kwargs={"k": RERANK_CANDIDATES})`. **Not `TOP_K`** — pulls a wider candidate pool for the `rerank` node to narrow down; a retriever built here without a following rerank step returns more documents than `TOP_K`. Hybrid/BM25 search still not implemented (README Phase 3 roadmap). |
| `vectorstore.py` | `VectorStoreFactory.load(embeddings)` → `FAISS.load_local(FAISS_PATH, embeddings, allow_dangerous_deserialization=True)`. **Load only — no build/ingest logic here.** |
| ~~`rag_pipeline_archived.py`~~ | **Removed 2026-07-24** (`git rm`, recoverable from history). Was dead code — not imported anywhere in the active codebase, and non-importable as-is (imported `get_embeddings`/`get_llm` functions that no longer exist in `embeddings.py`/`llm.py`). It was the direct ancestor of today's node-based workflow: a single `RAGPipeline` class doing retrieval + a combined intent/response prompt + memory update in one `.query()` method. |

**Active retrieval + generation flow:**

```
query → guardrails → intent
     → (knowledge) query rewrite (maybe) → retriever.invoke()
     against faiss_index/ → concatenated context
     → build_generation_prompt → Groq LLM → JSON-parsed answer → memory update
```

---

## 5. Guardrails — `src/guardrails/`

`base.py` — `BaseValidator.validate(state: RAGState) -> RAGState` (ABC).

`input_guardrail.py` — `InputGuardrail` runs an ordered validator chain,
short-circuiting on the first failure (`is_valid=False`):

1. **`EmptyQueryValidator`** (`validators/empty_query.py`) — rejects blank/whitespace-only queries.
2. **`LengthValidator`** (`validators/length.py`) — rejects queries over `MAX_QUERY_LENGTH = 512` chars.
3. **`CharacterValidator`** (`validators/character.py`) — strips control characters (`\x00`–`\x1f`, `\x7f`); mutates rather than rejects.
4. **`PromptInjectionValidator`** (`validators/prompt_injection.py`) — regex-blocks phrases like "ignore previous instructions", "forget previous instructions", "system prompt", "developer mode", "act as", "jailbreak".
5. **`QueryNormalizer`** (`validators/normalizer.py`) — collapses whitespace, strips; mutates rather than rejects.

Rejected queries route straight to `guardrail_response` and never reach
intent detection or retrieval. Planned but not yet implemented (per README):
PII detection, toxicity detection, language detection, sensitive-information
detection, role validation.

---

## 6. Evaluation — `src/evaluation/`

- **`models.py`** — `EvaluationResult` dataclass: `query`, `category`,
  `response`, `latency`, `success`, `metadata`, `.to_dict()`.
- **`runner.py`** — `EvaluationRunner` loads
  `src/evaluation/datasets/workflow_test_suite.json`, instantiates a real
  `RAGService`, and for each case calls `rag.ask(query, return_state=True)`
  to get the full workflow end state, timing latency via
  `time.perf_counter()` and catching exceptions as `success=False`. Results
  collect into a pandas DataFrame and write to
  `src/evaluation/results/evaluation_<timestamp>.csv`.

  ```bash
  python -m src.evaluation.runner
  ```

- **`datasets/workflow_test_suite.json`** — categories: `knowledge`,
  `greeting`, `chit_chat`, `guardrail_empty`, `guardrail_whitespace`,
  `guardrail_long_query`, `guardrail_prompt_injection`, `normalization`,
  `out_of_context`, `rewrite`.
- **`results/`** — 10 CSV snapshots (`evaluation_20260714_200150.csv` through
  `evaluation_20260715_203855.csv`), i.e. iterative runs captured as the
  workflow evolved on those two days.

---

## 7. Services, prompts, processing

- **`src/services/rag_service.py` — `RAGService`.** The public façade used by
  `main.py` and the evaluation runner. `__init__` builds memory, shared
  `resources`, and the compiled LangGraph. `.ask(query, return_state=False)`
  invokes the graph with an initial state built from `query`, returning
  either the plain answer string or the full final state (used by the
  evaluator). `.reset_memory()` clears conversation history.
- **`src/prompts/generation.py` — `build_generation_prompt(*, query, context, chat_history)`.**
  The knowledge-answer template: answer only from context, say "I don't
  know." if the context doesn't cover it, be concise, never reveal that
  context/reasoning was supplied.
- **`src/processing/query_rewriter.py` — `QueryRewriter`.** Singleton
  (`.get(resources)`), used only by the `process_query` node. Contains a
  cost-saving heuristic, `_needs_rewrite()`: skips the LLM call entirely
  unless chat history exists **and** the query contains a pronoun/reference
  token (`it, this, that, they, them, those, these, he, she, him, her, his,
  its, their`). When triggered, asks the LLM for a short keyword-style
  retrieval query with pronouns resolved from history
  (`{"rewritten_query": "..."}`); falls back to the original query on any
  failure. This is the "Query Rewriting" item under README's Phase 2 —
  partially landed.

---

## 8. Ingestion pipeline — version history (read this if anything about "how documents get in" is unclear)

This is the part the codebase itself doesn't document anywhere, and the part
most likely to confuse a new contributor: **there is currently no working
ingestion code inside this project.** `src/retrieval/vectorstore.py` only
loads an existing FAISS index (`FAISS.load_local`); nothing in the active
`src/` tree can build one. Ingestion has been fully spun out into the separate
[`smart-document-ingestion-engine`](https://github.com/yugmint/smart-document-ingestion-engine/blob/main/DOCUMENTATION.md) project.

Here is how it got there, oldest to newest.

### Stage 1 — monolithic script era (pre-`73c59e0`)

A flat `src/` with `ingestion_pipeline.py` and `rag_pipeline.py` doing
everything in one place. Was documented in `local/project_history/README_v3.md`
(deleted 2026-07-24, untracked local file, not recoverable — see §1).
`src/retrieval/rag_pipeline_archived.py` was the dead relic of this era's
`RAGPipeline` class, confirmed unused/non-importable; removed in the same
2026-07-24 cleanup pass (staged via `git rm`, so it's recoverable from git
history if ever needed — unlike the README above, which was never tracked).

### Stage 2 — placeholder split (commit `73c59e0`, *"seperated the ingestion and retiveal pipelines"*)

Created `src/ingestion/ingestion_pipeline.py` and moved
`config.py`/`embeddings.py`/`intent_classifier.py`/`llm.py`/`memory.py`/
`rag_pipeline.py`/`retriever.py`/`vectorstore.py` into the new
`src/retrieval/`. The new ingestion file, however, was committed **entirely
commented out** — a `build_vector_db()` sketch (PyPDFLoader →
RecursiveCharacterTextSplitter → FAISS), abandoned at the moment it was
created. It stayed dead code from this commit through HEAD.

### Stage 3 — real modular ingestion pipeline, committed (commit `5e12446`, current HEAD, *"added new ingestion pipeline along with validations and benchmarks"*)

A genuine modular ingestion package landed in `src/ingestion/`:
`chunkers/{base,hybrid_chunker,recursive_chunker}.py`,
`cleaners/{base,factory,text_cleaner}.py`, `embedders/embedder.py`,
`indexers/faiss_indexer.py`, `loaders/{base,factory,pdf_loader}.py`,
`metadata/generator.py`, `models.py`, `config.py`
(`IngestionConfig(chunk_strategy="recursive", chunk_size=500,
chunk_overlap=100, embedding_model="sentence-transformers/all-MiniLM-L6-v2",
vector_store="faiss", index_path="vectorstore")`), and `pipeline.py`
(`IngestionPipeline`, orchestrating loader → cleaner → chunker → metadata →
`FAISSIndexer.build`/`save`). This same commit also added
`src/processing/query_rewriter.py` and `src/workflow/nodes/process_query.py`
(§7) — i.e. the query-rewrite feature and this ingestion pipeline landed
together. **This is the version currently recorded in git**, but see Stage 4:
it has since been deleted from the working tree.

### Stage 4 — removed from the tree, and now removed for good

As of commit `aa19c6c` ("Remove in-tree ingestion pipeline; superseded by
standalone ingestion_fixed", 2026-07-24), the deletion of every file under
`src/ingestion/` (16 files) plus `local/test/cuda_test.py` and
`local/test/exp_notebook.ipynb` is committed — `git log` and the working
tree now agree that this repo has no ingestion code. (Previously this
deletion sat uncommitted for a while; see `docs/06-release-notes.md` and
`docs/04-contributing.md`'s Git hygiene section for why that was a problem
in its own right.)

Two zip archives briefly existed alongside the deletion, documenting the
transition:

- **`src/ingestion.zip`** (~71 KB, written 2026-07-22 00:06) — a raw backup
  of the working-tree state just before deletion; a superset of what's
  committed at `5e12446` (added `analysers/` and three more chunker
  strategies not yet in that commit).
- **`src/ingestion_fixed.zip`** (~34 KB, written 2026-07-22 00:41) — a
  restructured, standalone-packaged version with its own `README.md`,
  `Dockerfile`, `pyproject.toml`, `tests/`. **This was the direct source of
  the sibling `ingestion_fixed/` project.**

**Both zips were deleted in a 2026-07-24 cleanup pass** (untracked, not
git-recoverable) — by that point everything relevant about their contents
was already captured in this document, and `ingestion_fixed/` exists as a
fully realized, independent repo, so the zips had no remaining forward
value. If you ever need the exact byte-for-byte transitional snapshot
rather than what's written here, it's gone; what's written here is what's
left.

Also removed in that same cleanup pass, since they were confirmed broken
(`ImportError` on `src.ingestion.*`, which no longer exists on disk or in
git): **`local/tmp_debug_ingestion.py`**, **`local/tmp_pdf_debug.py`**,
**`src/test_ingestion.py`** — ad hoc debug/benchmark scripts from testing
Stage 3/4, all untracked.

### What this means in practice

| Approach | Status | Where it lives now |
|---|---|---|
| Inline `build_vector_db()` script | Legacy, dead | Comment-only in `src/ingestion/ingestion_pipeline.py`, itself removed at `aa19c6c` — recoverable via `git show 73c59e0:src/ingestion/ingestion_pipeline.py` if ever needed |
| Placeholder split (`73c59e0`) | Legacy, never implemented | Same as above |
| Modular pipeline v1 (`5e12446`) | Committed, then its removal also committed (`aa19c6c`) | Recoverable via `git show 5e12446` / `git log` if ever needed |
| Modular pipeline v2 (superset) | Was an uncommitted zip snapshot | Deleted 2026-07-24, not recoverable — see above |
| **Standalone packaged pipeline** | **Current / going forward** | Spun off as the sibling **`ingestion_fixed/`** project (see its own `DOCUMENTATION.md`) |

### The stale-index issue — fixed 2026-07-24, here's what it actually was

This repo used to have three separate FAISS index directories on disk, none
git-tracked, of very different vintages and quality. All three indexed the
same source document (`local/data/Grandma's Bag of Stories by Sudha
Murthy.pdf`), just built by different pipeline generations:

| Path (at the time) | Chunks | Built by | Verdict |
|---|---|---|---|
| `faiss_index/` (May build) | 466 | Stage 1, monolithic-script era | Structurally fine but pre-analyzer (no adaptive chunking, no rich metadata) |
| `vectorstore/` | 2656 | Stage 3's `IngestionPipeline`, same evening as `5e12446` | **The pre-fix pipeline** — avg chunk size 64 chars (489 of 2656 chunks under 50 chars), and `document_type: 'pdf'` everywhere: the exact metadata key-collision bug `ingestion_fixed/PATCH_NOTES.md` documents fixing. Confirmed by direct inspection of `index.pkl`. |
| `src/vectorstore/` | 2656 | Same pipeline, later run | Same bugs as above (identical build) |

(All three were renamed aside with a `.stale-*` suffix rather than deleted
immediately, specifically so this comparison could be double-checked before
committing to the fix. Once that verification was done, they were deleted
in the same 2026-07-24 cleanup pass as the zips above — untracked, not
git-recoverable. The numbers/verdicts above are what was captured before
deletion.)

The live app's `FAISS_PATH` pointed at the May index (`faiss_index/`) —
stale, but at least not structurally broken. **The "obvious" fix of just
repointing `FAISS_PATH` at the newer `vectorstore/` build would have made
retrieval *worse***, not better — it would have swapped merely-outdated
data for freshly-built but badly-fragmented, mislabeled data.

**Actual fix applied:** re-ran the current, fixed `ingestion_fixed` pipeline
against the source PDF —

```bash
cd ingestion_fixed
INGESTION_INDEX_PATH="../RAG_Project_1/faiss_index_v2" \
    python -m src.ingestion.pipeline "../RAG_Project_1/local/data/Grandma's Bag of Stories by Sudha Murthy.pdf"
```

— producing 314 chunks, 85–841 chars each (avg 641, target 700), zero
chunks under 50 chars, and correctly separated `document_type: 'general'` /
`file_extension: 'pdf'` metadata. That output was promoted to the canonical
`faiss_index/` path. `FAISS_PATH`'s default in `src/retrieval/config.py`
didn't need to change — it already pointed at `faiss_index/`, which now
contains good data. Verified end-to-end via `VectorStoreFactory.load()` →
`RetrieverFactory.build()` → `.invoke()` returning coherent, on-topic
chunks. (If you ever need to re-run this comparison yourself, note the old
buggy `vectorstore/`/`src/vectorstore/` builds are gone — you'd have to
rebuild them from the `5e12446` commit to reproduce the "before" state.)

**Lesson for next time a "stale index" is suspected:** don't assume the
newest-looking build is the best one — inspect `index.pkl`'s docstore
directly (`pickle.load` on it gives you the `InMemoryDocstore` and every
chunk's metadata) and check chunk size distribution and metadata sanity
before trusting it. This is exactly the class of problem
`ingestion_fixed/scripts/validate_chunks.py` exists to catch automatically
— worth running against any future rebuild instead of eyeballing file
timestamps.

---

## 9. Dependencies (`requirements.txt`)

| Category | Libraries |
|---|---|
| LLM provider | `langchain-groq` (Groq, model `llama-3.1-8b-instant`); `openai` is also listed but not used by any active code path found — likely leftover |
| Orchestration | `langchain`, `langchain-core`, `langchain-community`, `langchain-text-splitters`, `langchain-huggingface` |
| Embeddings | `sentence-transformers`, `transformers`, `tokenizers`, `huggingface-hub`, `torch`/`torchvision` (CPU build pinned here; `embeddings.py` auto-detects CUDA on the host if present) |
| Vector store | `faiss-cpu` |
| PDF/document parsing | `pymupdf`, `pypdf`, `unstructured` |
| Tokenization | `tiktoken` |
| Scientific stack | `numpy`, `pandas` (used by `evaluation/runner.py`), `scipy`, `scikit-learn` |
| Utilities | `python-dotenv`, `tqdm`, `requests` |
| Dev | `ipykernel`, `jupyter` |

> **Gap:** `workflow.py` imports `langgraph` directly, but `langgraph` is not
> listed in `requirements.txt`. Worth adding explicitly so a clean
> `pip install -r requirements.txt` actually works.

---

## 10. Git history — major phases

1. **Bootstrap** (`69f534a` → `552be68`) — initial commit, `.gitignore`/README cleanup (`cred.json`, `venv_rag` ignored).
2. **Ingestion/retrieval split** (`73c59e0`) — flat `src/` reorganized into `src/ingestion/` (placeholder) + `src/retrieval/` (the working LangChain pieces).
3. **Iterative LangChain-era hardening** (`081367a` → `5cd05ef`) — reference fixes, `main.py` fixes, removing a redundant LLM call in intent classification, JSON-structured responses.
4. **LangGraph foundation** (`9719177`, `46137e0`, `34c4714`, `c04f0c7`) — introduces `RAGState`, `RAGResources`, graph-based workflow replacing the single `RAGPipeline` class.
5. **Testing & cleanup** (`1e5ed5d`, `422151c`).
6. **Observability & robustness** (`a65328c` logger, `b642bde` fixed intent node for greeting/chit-chat, `27e969e` refactored factories + CUDA support).
7. **Guardrails + full modular workflow** (`dbcc9fd` *"feat: implement modular LangGraph workflow with input guardrails"*) — the architecture described in §3–5 as it exists today.
8. **Phase 1 completion** (`bd797f6`) — current root `README.md` reflects this milestone.
9. **New modular ingestion pipeline** (`5e12446`, HEAD) — built out `src/ingestion/` fully, added query rewriting — immediately followed (uncommitted, post-HEAD) by that same ingestion code being deleted from the working tree and archived/spun off into `ingestion.zip` and `ingestion_fixed.zip` (§8).

---

## 11. Running

```bash
python -m venv venv
pip install -r requirements.txt
```

Create `cred.json` at the repo root:

```json
{ "grok_api_key": "YOUR_GROQ_API_KEY" }
```

```bash
python main.py                      # interactive chat
python -m src.evaluation.runner     # run evaluation suite → src/evaluation/results/
```

To (re)build the vector index this app reads from, use the separate
[`smart-document-ingestion-engine`](https://github.com/yugmint/smart-document-ingestion-engine/blob/main/DOCUMENTATION.md) project — see its
`DOCUMENTATION.md` §7 for the CLI/Docker usage — then point
`src/retrieval/config.py`'s `FAISS_PATH` at the resulting index directory
(see the stale-index note in §8).

---

## 12. API deployment (`src/api.py`)

Alongside `main.py`'s interactive CLI, a FastAPI service exposes the RAG
workflow over HTTP — meant to be deployed as a standalone service, paired
with `smart-document-ingestion-engine`'s own API, both pointed at the same shared FAISS
index directory (§8's stale-index problem is exactly what this is meant to
finally fix, going forward). This is additive; `main.py` still works
unchanged.

- `GET /health` — unauthenticated (health checks shouldn't need a key).
- `POST /query` — `{"query": "...", "session_id": "..."}` → `{"answer", "intent", "status", "session_id"}`. `session_id` is optional; omit it to use one implicit shared session (same behavior as before session support existed).
- `POST /reload` — reloads the FAISS index from disk **in place**, without
  restarting the process. Works because `RAGResources` (`resources.py`) is a
  plain mutable dataclass and every workflow node closes over the same
  instance by reference — see `RAGService.reload_index()` in
  `src/services/rag_service.py`. Call this after an external ingestion run
  has written a fresh index to the path this service reads
  (`FAISS_INDEX_PATH`).
- `POST /reset-memory?session_id=...` — clears conversation history for one session (`RAGService.reset_memory()`).

All three non-health endpoints require an `X-API-Key` header matching the
`RAG_API_KEY` environment variable (`src/utils/auth.py`). If `RAG_API_KEY`
isn't set, they run unauthenticated with a loud startup warning — convenient
for local dev, not something to leave unset in any deployment reachable
beyond localhost.

Changes needed to make this deployable in a container, beyond adding the
API file itself:

- `src/retrieval/config.py`'s `FAISS_PATH` is now `os.getenv("FAISS_INDEX_PATH", "faiss_index")` instead of a hardcoded string, so a container can point it at a mounted volume.
- `src/retrieval/llm.py`'s `LLMFactory._load_api_key()` now skips reading `cred.json` if `GROQ_API_KEY` is already set in the environment — `cred.json` is gitignored and holds a secret, so baking it into an image isn't appropriate; containers should set `GROQ_API_KEY` directly instead. Local dev via `cred.json` still works unchanged.
- `src/utils/auth.py` (new) — the API key dependency described above.

### Conversation memory is now per-session — and this uncovered a real bug

`RAGResources` no longer holds a `memory` field. Memory is inherently
per-conversation, not a process-wide singleton like the LLM/embeddings/
vectorstore/retriever — keeping it on the shared, mutable `resources` object
would race under concurrent requests for different sessions. Instead,
`RAGService` keeps a `session_id -> InMemoryChatMessageHistory` dict
(`src/services/rag_service.py`), and the specific session's memory object is
carried through `RAGState["session_memory"]` for that one request/graph
invocation — a fresh dict per call, never shared across concurrent requests.
`nodes/update_memory.py` now reads/writes `state["session_memory"]` instead
of `resources.memory`.

**While wiring this up, a much bigger pre-existing bug surfaced:**
`RAGState["chat_history"]` was hardcoded to `""` in every call to
`RAGService.ask()`, and *nothing anywhere* ever populated it from the
conversation memory `update_memory` was dutifully writing to.
`src/utils/chat_history.py::format_chat_history` — exactly the function
needed to do this — existed in the codebase but was only ever called from
the dead `rag_pipeline_archived.py`, never from the live LangGraph path.
Net effect: conversation memory was **write-only** — every turn got
appended to `resources.memory`, but the next turn's query rewriter, intent
classifier, and generation prompt all saw an empty history regardless. This
wasn't a sharing/isolation bug, it was a complete no-op. Fixed as part of
this same change: `RAGService.ask()` now calls `format_chat_history()` on
the session's memory before building `initial_state`. Verified end-to-end —
a session asking "Who is X?" then "What did *she* do?" now correctly
resolves the pronoun via query rewriting using real prior-turn context, and
a second, unrelated session_id sees none of it.

`src/evaluation/runner.py` was updated to give each test case its own
`session_id` (`f"eval-{idx}-{category}"`) — now that `chat_history` actually
works, running all cases through one shared session would have let earlier
test cases' context leak into later ones, which isn't what independent test
cases should do.

### A second pre-existing bug found only by actually running the graph

`langgraph` had never actually been installed/run against this codebase in
this dev environment — installing it to test the above surfaced a
`StateGraph` node-naming collision: `workflow.py` registered a graph node
named `"intent"`, which collides with `RAGState`'s `intent` field (this
version of `langgraph` rejects that). Fixed by renaming the *node id* to
`"detect_intent"` in `workflow.py` (edges and conditional-routing keys
updated to match); the state field itself, and everything that reads
`state["intent"]`, is untouched. Also resolved: `langgraph` pinned to
`0.2.76` in `requirements.txt` — later `langgraph>=0.3` requires
`langchain-core>=1.0`, which conflicts with every other `langchain-*`
pin in this project (all require `<1.0.0`); `fastapi`/`uvicorn` pins were
corrected to the versions actually verified working (`0.139.2`/`0.51.0`).

Run locally:

```bash
uvicorn src.api:app --reload --port 8001
```

Containerized:

```bash
docker build -t rag-api .
docker run -p 8001:8001 -e GROQ_API_KEY=... -e RAG_API_KEY=... -v $(pwd)/data:/data rag-api
```

The `docker-compose.yml` for running both services together against a
shared named volume lives in the shared parent folder, not in this repo
(see `SETUP.md`, step 2). **Bootstrap order matters:** this service calls
`FAISS.load_local()` at startup and will fail to start against an empty
shared volume — ingest at least one document via the ingestion API first.
See the compose file's comments for the full sequence.
