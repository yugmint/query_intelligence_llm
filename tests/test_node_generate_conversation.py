"""
Tests for nodes/generate_conversation.py::generate_conversation.
"""

from tests.conftest import FakeLLM, make_resources

from src.workflow.nodes.generate_conversation import generate_conversation


def _state(**overrides):
    state = {"query": "hi there", "intent": "greeting", "chat_history": ""}
    state.update(overrides)
    return state


def test_returns_llm_content_directly():
    # Plain text, not JSON-wrapped -- see the node's docstring for why
    # (streaming compatibility; the JSON-wrapper instruction was never
    # reliably honored anyway).
    llm = FakeLLM("Hello! How can I help?")

    result = generate_conversation(_state(), make_resources(llm=llm))

    assert result["answer"] == "Hello! How can I help?"
    assert result["metadata"]["intent"] == "greeting"


def test_strips_surrounding_whitespace():
    llm = FakeLLM("  Hey! Just chatting.  \n")

    result = generate_conversation(_state(), make_resources(llm=llm))

    assert result["answer"] == "Hey! Just chatting."


def test_prompt_includes_intent_history_and_query():
    llm = FakeLLM("ok")
    state = _state(intent="chit_chat", chat_history="user: hi\nassistant: hey", query="what's up")

    generate_conversation(state, make_resources(llm=llm))

    prompt = llm.prompts[0]
    assert "chit_chat" in prompt
    assert "user: hi" in prompt
    assert "what's up" in prompt


def test_prompt_instructs_against_json_and_fences():
    # The whole point of this node's rewrite -- make sure the
    # instruction that made streaming safe doesn't silently disappear.
    llm = FakeLLM("ok")

    generate_conversation(_state(), make_resources(llm=llm))

    prompt = llm.prompts[0].lower()
    assert "json" in prompt
    assert "fence" in prompt
