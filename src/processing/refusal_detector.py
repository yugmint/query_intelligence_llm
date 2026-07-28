"""
Detects whether a generated answer is a hedge/refusal ("I don't know",
"not mentioned in the document", etc.) rather than a real answer.

Shared between scripts/benchmark.py (grading) and
nodes/generate_knowledge.py (refusal-triggered model escalation --
see src/retrieval/llm.py::LLMFactory.get_escalation) so the phrase
list only lives in one place.
"""

# Broader than a literal "i don't know" -- Level 6 "Failure Tests" cases
# (scripts/benchmark.py CASES, expect_refusal=True) expect a hedge/refusal
# phrased any number of ways ("not mentioned", "the document does not
# specify", "no information about", etc.), not that one exact sentence.
REFUSAL_PHRASES = [
    "i don't know",
    "not mentioned",
    "not specified",
    "not available",
    "not stated",
    "not provided",
    "no information",
    "does not mention",
    "does not specify",
    "does not provide",
    "does not state",
    "unclear from",
    "cannot determine",
    "unable to determine",
    "insufficient information",
    "no mention of",
    "the document does not",
    "not indicate",
]


def is_refusal(answer: str) -> bool:
    answer_lower = (answer or "").lower()
    return any(phrase in answer_lower for phrase in REFUSAL_PHRASES)
