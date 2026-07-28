"""
Per-token USD pricing for models this project calls, so real query cost
can be tracked (docs/05-roadmap.md v0.6.0, token efficiency). Groq
pricing, per million tokens, checked 2026-07-28 -- update if it changes:
https://groq.com/pricing
"""

# {model_name: (input $/token, output $/token)}
_PRICE_PER_TOKEN = {
    "llama-3.1-8b-instant": (0.05 / 1_000_000, 0.08 / 1_000_000),
    "openai/gpt-oss-20b": (0.075 / 1_000_000, 0.30 / 1_000_000),
}


def estimate_cost_usd(model_name: str, input_tokens: int, output_tokens: int) -> float | None:
    """
    None (not 0.0) for an unpriced model -- callers should skip/omit
    rather than silently report a wrong-but-plausible $0.00.
    """

    prices = _PRICE_PER_TOKEN.get(model_name)
    if prices is None:
        return None

    input_price, output_price = prices
    return input_tokens * input_price + output_tokens * output_price
