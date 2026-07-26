# 03 — Development Guide

## Setup

```bash
python -m venv venv
venv\Scripts\activate        # Windows
pip install -r requirements.txt
```

`requirements.txt` was missing `langgraph` entirely despite `workflow.py`
importing it directly — added (unpinned) as part of the API deployment work.
Pin it to whatever version you've actually developed against
(`pip show langgraph` in a working environment) before relying on this file
for a clean install. See §12 of `DOCUMENTATION.md`.

Create `cred.json` at the repo root for local dev (or set `GROQ_API_KEY`
directly — see `07-design-decisions.md` for why both paths exist now):

```json
{ "grok_api_key": "YOUR_GROQ_API_KEY" }
```

### Optional: local GPU acceleration

`requirements.txt` pins plain `torch==2.7.1`, which resolves to the
**CPU-only** build from PyPI — deliberately, since that's the only build
that installs cleanly everywhere (CI runners, most cloud deployment
targets, machines with no NVIDIA GPU). `EmbeddingFactory` and the
reranker both already auto-detect CUDA at runtime with zero code
changes needed — the only thing gating GPU use is which `torch` build
is actually installed.

If you have a working NVIDIA GPU + driver locally and want faster
retrieval during dev, install the CUDA build **on top of** the regular
install, matching the exact pinned version (don't let this drift to a
different `torch`/`torchvision` version — that risks breaking
compatibility with `sentence-transformers`/`transformers`):

```bash
pip install torch==2.7.1+cu126 torchvision==0.22.1+cu126 --index-url https://download.pytorch.org/whl/cu126
```

(`cu126` assumes a driver supporting CUDA 12.6+; check `nvidia-smi`'s
reported CUDA version and pick a matching build from
https://download.pytorch.org/whl/torch/ if different. This is a ~2.7GB
download.)

Real measured effect (GTX 1650, 4GB VRAM) — reranking (the dominant
cost in the retrieval path, see
`docs/reports/2026-07-24-reranking-validation.md` §5) dropped from
~700-725ms to **~125-180ms** per query, a genuine 4-5x speedup.
Trade-off: embedding-model startup went from ~17s to ~30s (one-time
CUDA context initialization, paid once at process start, not
per-query). This is purely a local-dev nicety — don't expect it to
carry into a $0-budget cloud deployment target, which almost certainly
won't have GPU access either.

**Windows-specific gotcha**: if `pip install` for the CUDA build fails
with `OSError: ... Access is denied` on a `torch\_C...pyd` file, close
VS Code (or any IDE with this venv selected as its Python interpreter)
first — Pylance/the Python extension holds a lock on installed
packages' binary files while indexing them, and Windows won't let pip
replace a file that's open elsewhere.

## You need a FAISS index before anything works

This repo has **no working ingestion code of its own** (see §8 of
`DOCUMENTATION.md` for why). `src/retrieval/vectorstore.py` only loads an
existing index from `FAISS_INDEX_PATH` (default `faiss_index/`). Before
`python main.py` or the API will do anything useful:

1. Use the sibling [`ingestion_fixed`](../../ingestion_fixed/DOCUMENTATION.md)
   project to build an index from your documents.
2. Point `FAISS_INDEX_PATH` (env var) or `src/retrieval/config.py`'s
   `FAISS_PATH` at the resulting directory.

Be aware there are currently **three different FAISS index directories** on
disk from different points in this project's history (`faiss_index/`,
`vectorstore/`, `src/vectorstore/`) — and the one actually wired up
(`faiss_index/`) is the oldest, smallest one. See §8 of `DOCUMENTATION.md`
for the full timeline before assuming retrieval quality issues are a code
bug rather than a stale-index problem.

## Running

```bash
python main.py                       # interactive CLI chat
uvicorn src.api:app --reload --port 8001   # HTTP API (added for standalone deployment)
python -m src.evaluation.runner      # evaluation suite -> src/evaluation/results/
```

## Tests

```bash
pytest tests/ -v
```

`tests/` (added 2026-07-24) covers the guardrail layer
(`test_guardrail_validators.py`, `test_input_guardrail.py`) and every
workflow node (`test_node_*.py`, one file per node, including
`test_node_rerank.py`) — 64 tests, all pure unit tests, no real
LLM/FAISS/reranker-model/network call. `conftest.py` has the shared
fakes:

- `FakeLLM` — stand-in for `resources.llm`; records every prompt, returns
  a scripted response (or raises, to test a failure path).
- `FakeRetriever` — stand-in for `resources.retriever`.
- `FakeReranker` — stand-in for `resources.reranker`; records every
  `(query, chunk)` batch it's asked to score, returns scripted scores.
- an autouse fixture resetting the `QueryRewriter` singleton between
  tests — it caches itself on the class (`QueryRewriter._instance`), so
  without this a `FakeLLM` from one test would leak into every later test
  that touches `process_query`.

`update_memory` tests use the real `InMemoryChatMessageHistory` rather than
a fake — it's a plain in-process object, nothing worth mocking.

A whitespace-based prompt-injection bypass found while writing these tests
(tracked as an `xfail` initially) is now fixed — see `07-design-decisions.md`
for what it was and how it was fixed without reordering the guardrail chain.

`src/evaluation/runner.py` against
`src/evaluation/datasets/workflow_test_suite.json` remains the only thing
exercising the full *compiled graph* end to end (guardrails, intent
routing, retrieval, generation) with latency/success recorded per case —
unit tests catch "this node's logic broke," the eval harness catches
"answer quality regressed." Keep using both.

## Working on the workflow graph

- Node functions live in `src/workflow/nodes/`, one file per node, each
  taking `(state, resources)` and returning a partial state update.
- Routing logic (`route_guardrail`, `route_by_intent`) lives directly in
  `workflow.py` next to `build_workflow` — keep new conditional routing
  there rather than scattering `if` branches inside node functions.
- `RAGState` (`state.py`) is the contract every node reads/writes against
  — declares `documents: list[Document]` for retrieval results (fixed
  2026-07-24; used to declare `retrieved_documents`/`reranked_documents`,
  which no node ever wrote — see `07-design-decisions.md`). If you add
  reranking (roadmap v0.2.0), add a real `reranked_documents` field then,
  not speculatively ahead of the implementation.

## Docker

```bash
docker build -t rag-api .
docker run -p 8001:8001 -e GROQ_API_KEY=... -v $(pwd)/data:/data rag-api
```

See the top-level `docker-compose.yml` (one directory up, alongside
`ingestion_fixed/`) to run this together with the ingestion API against a
shared volume. Bootstrap order matters — see that file's comments.
