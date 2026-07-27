import re

from src.guardrails.base import BaseValidator


# ponytail: regex covers common PII/secret shapes (email, phone, SSN,
# credit card, API-key-like tokens) -- not a real PII model (no names/
# addresses/free-text PII). Upgrade path: a proper NER-based detector
# (e.g. Presidio) if regex misses matter in practice.
PATTERNS = [
    r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",  # email
    r"\b\d{3}-\d{2}-\d{4}\b",  # SSN
    r"\b\+?1?[ -]?\(?\d{3}\)?[ -]?\d{3}[ -]?\d{4}\b",  # US phone
    r"\bsk-[a-zA-Z0-9]{20,}\b",  # OpenAI-style API key
    r"\bAKIA[0-9A-Z]{16}\b",  # AWS access key
]

_COMPILED = [re.compile(p) for p in PATTERNS]

# Credit card: grouped-digit shape first, THEN a Luhn check -- a bare
# "13-16 digits" regex would false-positive on ISBNs, order numbers,
# etc. Luhn is a few lines, not a dependency, and is the actual
# real-world check card numbers satisfy.
_CARD_SHAPE = re.compile(r"\b(?:\d[ -]?){12,18}\d\b")


def _luhn_valid(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


class SensitiveInfoValidator(BaseValidator):

    def validate(self, state):

        query = state.get("query", "")
        reason = None

        if any(p.search(query) for p in _COMPILED):
            reason = "email, phone, SSN, or API key"
        else:
            for match in _CARD_SHAPE.finditer(query):
                digits = re.sub(r"[ -]", "", match.group())
                if 13 <= len(digits) <= 19 and _luhn_valid(digits):
                    reason = "a card number"
                    break

        if reason:
            state["is_valid"] = False
            state["guardrail_reason"] = (
                f"Query appears to contain sensitive information ({reason}) "
                "-- please remove it and try again."
            )

        return state
