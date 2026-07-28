from src.utils.pricing import estimate_cost_usd


def test_known_model_computes_real_cost():
    cost = estimate_cost_usd("llama-3.1-8b-instant", input_tokens=1_000_000, output_tokens=1_000_000)
    assert cost == 0.05 + 0.08


def test_zero_tokens_is_zero_cost():
    assert estimate_cost_usd("llama-3.1-8b-instant", 0, 0) == 0.0


def test_unknown_model_returns_none_not_zero():
    # None, not 0.0 -- a silent $0.00 for an unpriced model would look
    # like a real (wrong) answer rather than "cost unknown".
    assert estimate_cost_usd("some-future-model", 100, 100) is None


def test_escalation_model_priced_higher_than_primary():
    primary = estimate_cost_usd("llama-3.1-8b-instant", 1000, 1000)
    escalation = estimate_cost_usd("openai/gpt-oss-20b", 1000, 1000)
    assert escalation > primary
