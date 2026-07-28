"""
Tests for src/processing/comparison_question.py.
"""

import pytest

from src.processing.comparison_question import extract_comparison_sides, is_implicit_comparison


@pytest.mark.parametrize(
    "query,expected",
    [
        ("Compare Harappan and Vedic societies.", ("Harappan", "Vedic societies")),
        ("Compare monarchy and Ganasanghas.", ("monarchy", "Ganasanghas")),
        ("Compare Harappan art with Mauryan art.", ("Harappan art", "Mauryan art")),
        (
            "What is the difference between Harappan and Vedic religion?",
            ("Harappan", "Vedic religion"),
        ),
        ("How did Early Vedic differ from Later Vedic?", ("Early Vedic", "Later Vedic")),
    ],
)
def test_extracts_explicit_sides(query, expected):
    assert extract_comparison_sides(query) == expected


@pytest.mark.parametrize(
    "query",
    [
        "What is factor analysis?",
        "Which civilization used bronze extensively?",  # synonym-style, not comparative
        "Compare Stone Age technology across all three phases.",  # 3-way, not 2 named sides
    ],
)
def test_no_explicit_sides(query):
    assert extract_comparison_sides(query) is None


@pytest.mark.parametrize(
    "query",
    [
        "Which civilization had the better drainage system?",
        "Which era gave women greater freedom?",
        "Which civilization had better trade networks?",
        "Which period had the greatest technological leap?",
    ],
)
def test_detects_implicit_comparison(query):
    assert is_implicit_comparison(query) is True


@pytest.mark.parametrize(
    "query",
    [
        "What is factor analysis?",
        "Which civilization left undeciphered inscriptions?",  # "which X" but no superlative
        "Compare Harappan and Vedic societies.",  # explicit, not implicit
    ],
)
def test_no_implicit_comparison(query):
    assert is_implicit_comparison(query) is False


def test_real_benchmark_l2_multi_hop_compare_cases_all_extract_sides():
    """
    Regression guard using the real, hand-verified benchmark set
    (scripts/benchmark.py) -- every "Compare X and Y"-phrased L2 case
    must extract two real sides, not silently fall through to no
    comparison detection at all.
    """
    from scripts.benchmark import CASES

    # "...across all three phases" is a deliberate, known exception --
    # a 3-way comparison has no 2 sides to extract, and falls back to
    # normal (unwidened) retrieval rather than crashing or misparsing.
    compare_cases = [
        c
        for c in CASES
        if c["level"] == "L2-Multi-hop"
        and c["question"].lower().startswith("compare")
        and "three phases" not in c["question"]
    ]
    assert len(compare_cases) > 0

    not_extracted = [c["question"] for c in compare_cases if extract_comparison_sides(c["question"]) is None]
    assert not_extracted == []


def test_real_benchmark_l5_cross_document_implicit_cases_all_detected():
    """
    Regression guard: the real L5-Cross-document cases that motivated
    this feature (see docs/05-roadmap.md v0.6.0) must still be detected
    as implicit comparisons.
    """
    from scripts.benchmark import CASES

    cross_doc_cases = [c for c in CASES if c["level"] == "L5-Cross-document"]
    assert len(cross_doc_cases) > 0

    superlative_cases = [
        c
        for c in cross_doc_cases
        if any(
            w in c["question"].lower()
            for w in ("better", "greater", "greatest", "more", "best", "worst")
        )
    ]
    assert len(superlative_cases) > 0

    not_detected = [
        c["question"]
        for c in superlative_cases
        if extract_comparison_sides(c["question"]) is None and not is_implicit_comparison(c["question"])
    ]
    assert not_detected == []
