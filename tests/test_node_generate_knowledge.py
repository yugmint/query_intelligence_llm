"""
Tests for nodes/generate_knowledge.py::generate_knowledge_response.
"""

from tests.conftest import FakeLLM, make_resources

from src.workflow.nodes.generate_knowledge import generate_knowledge_response


def _state(**overrides):
    state = {
        "query": "what does the book say about X?",
        "context": "X is mentioned on page 5.",
        "chat_history": "",
    }
    state.update(overrides)
    return state


def test_valid_json_response_extracts_answer():
    llm = FakeLLM('{"response": "X is described on page 5."}')

    result = generate_knowledge_response(_state(), make_resources(llm=llm))

    assert result["answer"] == "X is described on page 5."
    assert result["metadata"]["response_length"] == len("X is described on page 5.")


def test_non_json_response_falls_back_to_raw_content():
    llm = FakeLLM("Just a plain-text answer, not JSON.")

    result = generate_knowledge_response(_state(), make_resources(llm=llm))

    assert result["answer"] == "Just a plain-text answer, not JSON."


def test_json_without_response_key_falls_back_to_raw_content():
    # json.loads succeeds but .get("response", content) has nothing to
    # find, so the whole (still-JSON) content is used as the answer.
    llm = FakeLLM('{"unexpected_key": "value"}')

    result = generate_knowledge_response(_state(), make_resources(llm=llm))

    assert result["answer"] == '{"unexpected_key": "value"}'


def test_prompt_includes_query_context_and_history():
    llm = FakeLLM('{"response": "ok"}')
    state = _state(chat_history="user: hi\nassistant: hello")

    generate_knowledge_response(state, make_resources(llm=llm))

    prompt = llm.prompts[0]
    assert "what does the book say about X?" in prompt
    assert "X is mentioned on page 5." in prompt
    assert "user: hi" in prompt


def test_existing_metadata_is_preserved():
    llm = FakeLLM('{"response": "ok"}')
    state = _state(metadata={"intent": "knowledge"})

    result = generate_knowledge_response(state, make_resources(llm=llm))

    assert result["metadata"]["intent"] == "knowledge"
    assert "response_length" in result["metadata"]


def test_refusal_retries_with_escalation_llm_and_uses_its_answer():
    llm = FakeLLM("I don't know.")
    escalation_llm = FakeLLM('{"response": "The Harappan Civilization."}')

    result = generate_knowledge_response(
        _state(), make_resources(llm=llm, escalation_llm=escalation_llm)
    )

    assert result["answer"] == "The Harappan Civilization."
    assert result["metadata"]["escalated"] is True
    assert escalation_llm.call_count == 1


def test_escalation_llm_also_refusing_keeps_original_refusal():
    llm = FakeLLM("I don't know.")
    escalation_llm = FakeLLM("I don't know.")

    result = generate_knowledge_response(
        _state(), make_resources(llm=llm, escalation_llm=escalation_llm)
    )

    assert result["answer"] == "I don't know."
    assert result["metadata"]["escalated"] is False


def test_escalation_llm_failure_falls_back_to_primary_refusal():
    llm = FakeLLM("I don't know.")
    escalation_llm = FakeLLM(RuntimeError("Groq 429"))

    result = generate_knowledge_response(
        _state(), make_resources(llm=llm, escalation_llm=escalation_llm)
    )

    assert result["answer"] == "I don't know."
    assert result["metadata"]["escalated"] is False


def test_no_escalation_llm_configured_skips_retry():
    llm = FakeLLM("I don't know.")

    result = generate_knowledge_response(_state(), make_resources(llm=llm))

    assert result["answer"] == "I don't know."
    assert result["metadata"]["escalated"] is False


def test_confident_answer_never_triggers_escalation():
    llm = FakeLLM('{"response": "X is described on page 5."}')
    escalation_llm = FakeLLM('{"response": "should never be called"}')

    result = generate_knowledge_response(
        _state(), make_resources(llm=llm, escalation_llm=escalation_llm)
    )

    assert result["answer"] == "X is described on page 5."
    assert escalation_llm.call_count == 0
