import re

from src.guardrails.base import BaseValidator


# ponytail: wordlist, not a real toxicity classifier -- catches blunt
# slurs/profanity, misses coded/implicit toxicity and false-positives on
# reclaimed words in legit questions. Upgrade path: a real classifier
# (Perspective API / a small local model) if this proves too coarse.
BLOCKED_WORDS = [
    "fuck", "shit", "bitch", "asshole", "cunt", "nigger", "faggot", "retard",
]

_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(w) for w in BLOCKED_WORDS) + r")",
    re.IGNORECASE,
)


class ToxicityValidator(BaseValidator):

    def validate(self, state):

        query = state.get("query", "")

        if _PATTERN.search(query):

            state["is_valid"] = False

            state["guardrail_reason"] = "Query contains offensive language."

        return state
