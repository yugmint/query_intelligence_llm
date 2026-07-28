import os

MODEL_NAME = "llama-3.1-8b-instant"
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
FAISS_PATH = os.getenv("FAISS_INDEX_PATH", "faiss_index")

# Final number of chunks that reach the generation prompt, after reranking.
TOP_K = 3

# How many candidates FAISS's plain cosine-similarity search pulls before
# reranking narrows them down to TOP_K. Needs to be meaningfully larger
# than TOP_K -- the whole point of reranking is to recover a genuinely
# relevant chunk that similarity search alone ranked outside the old,
# un-reranked top-3 (confirmed happening in practice: see
# docs/reports/2026-07-24-academic-document-e2e-test.md and
# docs/reports/2026-07-24-efficientnet-research-paper-e2e-test.md).
RERANK_CANDIDATES = int(os.getenv("RERANK_CANDIDATES", "15"))

# Cross-encoder reranker model. Scores (query, chunk) pairs jointly, which
# is much more precise than the bi-encoder similarity search FAISS does --
# that's the entire reason reranking helps. Small/fast, same weight class
# as EMBEDDING_MODEL above, and ships inside the sentence-transformers
# package already listed in requirements.txt -- no new dependency.
RERANK_MODEL = os.getenv("RERANK_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2")

# Widened retrieval/rerank budget used only for numeric questions (see
# src/processing/numeric_question.py) -- a real, reproduced failure:
# for "what was the sample size?" against a real document, the correct
# chunk ranked ~65th/84 by FAISS's bi-encoder similarity search alone (a
# nearby distractor sentence lexically repeats "sample size" three times;
# the correct sentence never uses that phrase) and only #8 among ALL 84
# chunks after cross-encoder reranking -- nowhere near reachable at the
# default RERANK_CANDIDATES=15/TOP_K=3. This widened budget is a
# best-effort mitigation confirmed to fix that specific case, not a
# guarantee: an even deeper miss on a larger document could still slip
# past it. Only applied when is_numeric_question() matches, so the
# latency cost (measured: ~0.7s vs ~0.24s reranking time on an 84-chunk
# document) is paid only by the narrow class of queries actually at risk,
# not every query. See docs/05-roadmap.md v0.2.0.
RERANK_CANDIDATES_NUMERIC = int(os.getenv("RERANK_CANDIDATES_NUMERIC", "80"))
TOP_K_NUMERIC = int(os.getenv("TOP_K_NUMERIC", "8"))

# How textually similar two candidate chunks need to be (difflib
# SequenceMatcher ratio, 0-1) before nodes/rerank.py treats the
# lower-scoring one as a near-duplicate and skips it in favor of the
# next-best distinct chunk -- see docs/05-roadmap.md v0.2.0 "chunk
# dedup/diversity". Chunk overlap (RecursiveChunker's chunk_overlap,
# ~15-22% of chunk_size across ingestion_fixed's profiles) means
# adjacent real chunks routinely share a literal head/tail substring;
# 0.8 sits well above what that alone produces, so normal overlap isn't
# flagged -- only chunks that are near-total duplicates of each other
# (e.g. genuinely redundant content, or the same passage re-embedded).
CHUNK_DEDUP_SIMILARITY_THRESHOLD = float(os.getenv("CHUNK_DEDUP_SIMILARITY_THRESHOLD", "0.8"))

# Reciprocal Rank Fusion constant for hybrid search (BM25 + dense) --
# see src/retrieval/hybrid.py. Dampens the influence of exact rank
# position; 60 is the standard default from the original RRF paper, not
# tuned specifically for this project.
RRF_K = int(os.getenv("RRF_K", "60"))

# How many neighboring chunks (by chunk_id, each side) parent-child
# retrieval pulls in around each matched chunk (src/retrieval/
# parent_context.py). v1 expanded to the whole parent *page* instead;
# found on a real book that most pages exceed a size cap and the whole
# mechanism fell back to "matched chunk only" almost every time (dense
# pages, not sparse ones, are exactly what this needs to help on). Count-
# bounded instead of size-bounded: worst case at TOP_K_NUMERIC=8 wholly-
# distinct matches is 8*(2*1+1)=24 chunks (~500 chars each) -- comfortably
# under the 6000 TPM ceiling that caused a real Groq 413 with v1's
# unbounded-by-density page expansion.
PARENT_CONTEXT_NEIGHBOR_CHUNKS = int(
    os.getenv("PARENT_CONTEXT_NEIGHBOR_CHUNKS", "1")
)

pdf_path = "data\Grandma's Bag of Stories by Sudha Murthy.pdf"  ## Paste your pdf path here
