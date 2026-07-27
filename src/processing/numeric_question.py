"""
Detects questions that ask for a specific number (a count, size, rate,
percentage, duration, etc.).

Exists because of a real, reproduced failure (docs/05-roadmap.md v0.2.0,
"distractor-number ranking gap"): a query like "what was the sample
size?" can have its one correct source sentence buried far outside the
default retrieval/rerank budget when a nearby, more lexically-matching
distractor sentence exists (e.g. one that repeats "sample size" verbatim
while the correct sentence doesn't). Widening that budget for every
query would cost every user real latency for a narrow failure mode; this
lets the workflow widen it only for the query shapes actually at risk.

Deliberately a fast, deterministic keyword/pattern match rather than an
LLM classification call -- this needs to run on every query without
adding a second model round-trip, and precision matters more than
recall here (a missed numeric question just gets the old default
behavior, no worse than before this existed; a false positive pays
the widened-budget latency cost for no benefit).
"""

import re

_NUMERIC_PATTERNS = [
    r"\bhow many\b",
    r"\bhow much\b",
    r"\bhow long\b",
    r"\bhow old\b",
    r"\bhow often\b",
    r"\bsample size\b",
    r"\bnumber of\b",
    r"\btotal number\b",
    r"\bwhat percentage\b",
    r"\bwhat proportion\b",
    r"\bwhat (?:is|was|are|were) the (?:number|total|count|size|percentage|proportion|rate|dose|dosage|amount)\b",
]

_NUMERIC_RE = re.compile("|".join(_NUMERIC_PATTERNS), re.IGNORECASE)


def is_numeric_question(query: str) -> bool:
    """
    True if `query` is asking for a specific number. Matched against the
    raw string -- callers should pass the same rewritten/original query
    used for retrieval, not chat history.
    """

    return bool(_NUMERIC_RE.search(query))
