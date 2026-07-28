"""
Classifies a query as "greeting"/"chit_chat"/"knowledge" without an LLM
call.

Real motivation: `nodes/intent.py` used to spend a full Groq round-trip
on this for every single query -- and `workflow.py::route_by_intent`
only ever asks a binary question of the result ("knowledge" -> retrieve,
anything else -> conversation), so a 3-way LLM classification was
answering a question nobody downstream needed answered at that
resolution. Removing that call halves the LLM calls per knowledge query
(2 -> 1), which matters a lot here specifically: the shared rate limiter
(src/retrieval/llm.py, sized for the real 6,000 TPM Groq free-tier
ceiling under concurrent traffic) burns 2 tokens per knowledge query
against a bucket that only refills 1 token per ~12.5s -- so every
second sequential query was paying a real ~25s wait for that budget to
refill, on top of actual inference time.

Deliberately biased toward "knowledge", the safe direction: matching a
real question as conversation would skip retrieval entirely and answer
ungrounded (wrong direction to be wrong in). Matching a real greeting
as knowledge just costs an unnecessary (cheap) retrieval pass -- still
answers fine, see nodes/generate_conversation.py's fallback shape isn't
even needed since "knowledge" routing handles it. Only classifies
conversation when the *entire* (trimmed, case-insensitive) message
matches a known short greeting/chit-chat pattern -- a real question
that merely starts with "Hi, ..." still classifies as knowledge, since
the whole message doesn't match.
"""

import re

_GREETING_PATTERNS = [
    r"h(i|ey|ello|iya|owdy)(\s+there)?",
    r"good (morning|afternoon|evening|night)",
    r"yo",
]

_CHIT_CHAT_PATTERNS = [
    r"(bye|goodbye|see you|take care|farewell)",
    r"(thanks|thank you|thx|ty)",
    r"(ok|okay|cool|nice|great|got it|sounds good|awesome)",
    r"how'?s?( it going| things| you doing| are you)",
    r"what'?s up",
    r"who are you",
    r"what can you do",
    r"(lol|haha)",
]


def _compile(patterns):
    return re.compile(r"^(" + "|".join(patterns) + r")[\s!.,?]*$", re.IGNORECASE)


_GREETING_RE = _compile(_GREETING_PATTERNS)
_CHIT_CHAT_RE = _compile(_CHIT_CHAT_PATTERNS)


def classify_intent(query: str) -> str:
    """
    Returns "greeting", "chit_chat", or "knowledge" (the default/safe
    fallback for anything that doesn't confidently match a short
    greeting/chit-chat phrase in its entirety).
    """

    normalized = (query or "").strip()

    if _GREETING_RE.match(normalized):
        return "greeting"

    if _CHIT_CHAT_RE.match(normalized):
        return "chit_chat"

    return "knowledge"
