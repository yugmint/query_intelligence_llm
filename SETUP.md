# Setup Guide — Demo Environment

For a new developer setting up these two repos on their own machine to
prepare for a stakeholder demo. Covers clone → dependencies →
credentials → getting a working index → running everything → verifying
it works.

Two repos, two jobs:

- **`ingestion_fixed`** — turns a document (PDF/txt/html/docx) into a
  FAISS vector index.
- **`RAG_Project_1`** — answers questions against that index.

They're independent git repos coupled only by sharing one FAISS index
directory on disk (see `docker-compose.yml` for the containerized
version of this setup — this guide covers the simpler non-Docker path,
which is what's actually been used for demo prep so far).

---

## 1. Prerequisites

- **Python 3.11** (confirmed working version — `python --version`)
- **git**
- **A Groq API key** — free at [console.groq.com](https://console.groq.com).
  Ask whoever's running the demo whether to use a shared key or get
  your own; either works, but a shared key means you share its daily
  quota (see the gotcha at the bottom).

## 2. Clone both repos

```bash
git clone https://github.com/yugmint/query_intellience_llm.git RAG_Project_1
git clone https://github.com/yugmint/smart-document-ingestion-engine.git ingestion_fixed
```

Put them side by side in the same parent folder — some tooling
(`docker-compose.yml`, path references in docs) assumes that layout.

**Important — this alone does not get you the demo UI.** The
`frontend/` folder (the actual chat interface used in demos),
`docker-compose.yml`, and this `SETUP.md` all live in a shared parent
folder that is *not* a git repo and isn't tracked anywhere — `git
clone` of the two repos above gets you both backend services and
nothing else. You need these copied to you directly (see step 5,
same manual-copy situation as the FAISS index) — ask whoever's running
the demo for the whole parent folder, or at minimum the `frontend/`
subfolder.

## 3. Python environment

One shared virtual environment for both repos is simplest (their
dependencies overlap heavily — same LangChain/embedding stack):

```bash
cd RAG_Project_1
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # macOS/Linux

pip install -r requirements.txt
pip install -r ../ingestion_fixed/requirements.txt
```

## 4. Credentials

Inside `RAG_Project_1/`, create `cred.json` (gitignored — never commit
this):

```json
{
    "grok_api_key": "YOUR_GROQ_API_KEY"
}
```

(Yes, the key in the JSON is `grok_api_key`, not `groq_api_key` — a
pre-existing naming quirk in the code, not a typo here.)

## 5. Get a working FAISS index — the one real gotcha

**The FAISS index and the source PDF are both gitignored — cloning the
repos alone does *not* get you a working index.** Two ways to get one.

### Option A — rebuild it from the source PDF (recommended)

Ask whoever prepared the demo for the source PDF (`ede93-history.pdf`)
and `frontend/` (the chat UI — see the note in step 2, this isn't in
either git repo). Then:

```bash
cd ingestion_fixed
python -m src.ingestion.pipeline path/to/ede93-history.pdf
```

This writes a fresh index to `vectorstore/` (or wherever
`INGESTION_INDEX_PATH` points, see step 6). **Confirmed reproducible**
against the exact index used in the last demo run: same 421 chunks,
same `document_type=book` classification (confidence 0.85), same
chunk_size (800) -- as long as `ingestion_fixed`'s classification/
chunking code hasn't changed since (check `git log -1 -- src/ingestion`
if you want to be sure). A single PDF is also a much smaller thing to
hand someone than a binary FAISS index folder, and running this
yourself doubles as a real smoke test that your ingestion setup
actually works.

### Option B — copy the pre-built index instead

If you'd rather not depend on reproducibility (e.g. the source has
since changed and you specifically need last week's snapshot), ask for
`ingestion_fixed/local/test_reports/history_book_index_v3/` (the
`.faiss` + `.pkl` files) directly and drop it anywhere on your
machine.

## 6. Run both APIs

Two separate terminals, both with the venv activated.

**Terminal 1 — RAG API** (from `RAG_Project_1/`):

```bash
set FAISS_INDEX_PATH=C:\path\to\history_book_index_v3      # Windows (cmd)
$env:FAISS_INDEX_PATH="C:\path\to\history_book_index_v3"   # Windows (PowerShell)
export FAISS_INDEX_PATH=/path/to/history_book_index_v3     # macOS/Linux

python -m uvicorn src.api:app --port 8001
```

**Terminal 2 — Ingestion API** (from `ingestion_fixed/`):

```bash
set INGESTION_INDEX_PATH=C:\path\to\history_book_index_v3
set RAG_RELOAD_URL=http://localhost:8001/reload

python -m uvicorn src.ingestion.api:app --port 8010
```

`INGESTION_INDEX_PATH` and `FAISS_INDEX_PATH` must point at the **same
folder** — that's the whole coupling mechanism between the two
services. `RAG_RELOAD_URL` is what makes a live ingest through the
frontend immediately show up in queries, without it you'd have to call
`/reload` by hand after every ingest.

Neither `RAG_API_KEY` nor `INGESTION_API_KEY` is set above — both
services run unauthenticated locally with a startup warning, which is
fine for a local demo. Don't do this for anything internet-facing.

Verify both are up:

```bash
curl http://localhost:8001/health
curl http://localhost:8010/health
# both -> {"status":"ok"}
```

## 7. Run the frontend

Static single-file HTML, no build step. Open `index.html` from
wherever you put the `frontend/` folder in step 5. It's pre-configured
to talk to `localhost:8001` (query) and `localhost:8010` (ingest) —
both should show green/connected if steps 4–6 worked.

## 8. Verify your setup is actually correct

```bash
cd RAG_Project_1 && pytest tests/ -v
cd ingestion_fixed && pytest tests/ -v
```

Both suites use fakes for the LLM/retriever — no API key or index
needed to run them, no real network calls. If these pass but the live
demo doesn't work, the problem is almost certainly in steps 4–6
(credentials, index path, or a port conflict), not the code itself.

Then a real smoke test against the live index — ask something you know
the answer to, e.g. (if using the history book):

```bash
curl -X POST http://localhost:8001/query -H "Content-Type: application/json" \
     -d '{"query": "Which Harappan site had the dockyard?", "session_id": "test"}'
# -> should mention "Lothal"
```

---

## Gotchas worth knowing before demo day

- **Groq's daily token quota (500,000 tokens/day, free tier) is
  shared across everyone using the same API key.** Heavy testing
  the day of the demo can exhaust it — if `/query` starts returning
  503s, that's the likely cause, not a bug. Check
  `console.groq.com` for remaining quota, or use a separate key for
  your own testing vs. the actual demo run.
- **The `faiss_index/` folder that `git clone` does *not* give you is
  the single most common setup failure.** If `/query` says "I don't
  have any documents loaded yet," `FAISS_INDEX_PATH` either isn't set
  or points at an empty/wrong folder.
- **Restart the API after changing `FAISS_INDEX_PATH`** — it's read
  once at process startup. Changing the *contents* of an index while
  the API is running is fine (that's what `/reload` is for); changing
  *which folder* it points at needs a restart.
- Full technical detail beyond this quickstart lives in each repo's
  `DOCUMENTATION.md` and `docs/` folder — `docs/03-development-guide.md`
  in particular.
