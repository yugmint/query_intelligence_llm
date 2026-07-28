"""
Tests for nodes/intent.py::detect_intent. No LLM call anymore -- see
src/processing/intent_classifier.py for why. resources isn't used by
this node at all now, so these tests pass make_resources() with
nothing set, unlike before.
"""

from tests.conftest import make_resources

from src.workflow.nodes.intent import detect_intent


def test_greeting_classified_without_llm_call():
    state = {"query": "hi there", "chat_history": ""}

    result = detect_intent(state, make_resources())

    assert result["intent"] == "greeting"
    assert result["metadata"]["intent"] == "greeting"


def test_chit_chat_classified():
    state = {"query": "how's it going", "chat_history": ""}

    result = detect_intent(state, make_resources())

    assert result["intent"] == "chit_chat"


def test_real_question_classified_as_knowledge():
    state = {"query": "what is the capital of France?", "chat_history": ""}

    result = detect_intent(state, make_resources())

    assert result["intent"] == "knowledge"


def test_question_starting_with_greeting_word_stays_knowledge():
    # The whole message isn't just a greeting -- must not be
    # short-circuited into skipping retrieval.
    state = {"query": "Hi, what were the main causes of the French Revolution?", "chat_history": ""}

    result = detect_intent(state, make_resources())

    assert result["intent"] == "knowledge"


def test_existing_metadata_is_preserved():
    state = {"query": "hi", "chat_history": "", "metadata": {"session_id": "abc"}}

    result = detect_intent(state, make_resources())

    assert result["metadata"]["session_id"] == "abc"
    assert result["metadata"]["intent"] == "greeting"
