"""
Detects comparison-shaped questions and, where the question names its
two sides explicitly, extracts them for a split-and-merge retrieval
pass. See nodes/retrieve_context.py.

Two real shapes found in this project's own benchmark (see
docs/05-roadmap.md v0.6.0, "comparison-aware retrieval"):

  Explicit ("Compare X and Y", "X vs Y", "difference between X and Y")
  -- both sides are named, so retrieval can run once per side and
  merge the results, giving each side a fair chance to surface its own
  top candidates instead of one side dominating a single ranked list.

  Implicit ("Which X had the better/more Y?") -- no named sides at
  all (the correct answer might be any of several civilizations/
  periods covered in the document), so there's nothing to split
  retrieval by. Widening k (same lever the existing numeric-question
  path already uses) is the only thing that helps here: a broader
  candidate pool is more likely to include content on more than one
  candidate answer. Confirmed this is the real shape of this project's
  actual failing cases -- every L5-Cross-document benchmark question
  is this implicit form, not the explicit one.
"""

import re

_EXPLICIT_RE = re.compile(
    r"compare (.+?) (?:and|with) (.+?)[\?.]?$|"
    r"difference between (.+?) and (.+?)[\?.]?$|"
    r"how did (.+?) differ from (.+?)[\?.]?$",
    re.IGNORECASE,
)

_IMPLICIT_RE = re.compile(
    r"\bwhich\b.{0,40}\b(had|has|gave|showed|demonstrated|left|saw)\b.{0,40}"
    r"\b(more|better|greater|best|worst|greatest|least|highest|lowest|fewer)\b",
    re.IGNORECASE,
)


def extract_comparison_sides(query: str) -> tuple[str, str] | None:
    """
    Returns (side_a, side_b) if the query explicitly names two things
    being compared, else None.
    """

    match = _EXPLICIT_RE.search(query or "")
    if not match:
        return None

    groups = [g for g in match.groups() if g]
    if len(groups) != 2:
        return None

    return groups[0].strip(), groups[1].strip()


def is_implicit_comparison(query: str) -> bool:
    """
    True for a superlative comparison with no named sides ("which X had
    the better Y?"). Callers should check extract_comparison_sides()
    first -- this only signals "widen the candidate pool," not "split
    retrieval," and the two are mutually exclusive by construction.
    """

    return bool(_IMPLICIT_RE.search(query or ""))
