"""
Tests for src/processing/intent_classifier.py::classify_intent.
"""

import pytest

from src.processing.intent_classifier import classify_intent


@pytest.mark.parametrize(
    "query",
    ["hi", "Hi!", "hello", "hey", "yo", "good morning", "Good Evening.", "howdy"],
)
def test_greetings(query):
    assert classify_intent(query) == "greeting"


@pytest.mark.parametrize(
    "query",
    [
        "bye", "goodbye", "thanks", "thank you!", "thx", "ok", "okay", "cool",
        "great", "how are you?", "what's up", "who are you?", "what can you do?",
        "lol", "haha",
    ],
)
def test_chit_chat(query):
    assert classify_intent(query) == "chit_chat"


@pytest.mark.parametrize(
    "query",
    [
        "what is the capital of France?",
        "Explain the causes of the French Revolution.",
        "Hi, what were the main causes of the French Revolution?",  # starts with a greeting word, but isn't one
        "Thanks, now can you tell me about the Harappan civilization?",
        "",
        "   ",
        "asdkfjalksdjf random gibberish query",
    ],
)
def test_defaults_to_knowledge(query):
    assert classify_intent(query) == "knowledge"


def test_case_insensitive_and_tolerates_trailing_punctuation():
    assert classify_intent("HELLO!!!") == "greeting"
    assert classify_intent("Thank You.") == "chit_chat"


def test_real_benchmark_question_set_never_misclassified_as_non_knowledge():
    """
    Regression guard using the real, hand-verified 97-question benchmark
    set (scripts/benchmark.py) built this session -- every one of these
    is a genuine question that must retrieve real document context.
    Misclassifying any of them as greeting/chit_chat would skip
    retrieval entirely and answer ungrounded, the unsafe direction to
    be wrong in (see the module's own docstring on why the classifier
    is deliberately biased toward "knowledge").
    """
    from scripts.benchmark import CASES

    misclassified = [
        c["question"] for c in CASES if classify_intent(c["question"]) != "knowledge"
    ]

    assert misclassified == []
