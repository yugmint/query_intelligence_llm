import pytest

from src.processing.refusal_detector import is_refusal


@pytest.mark.parametrize(
    "answer",
    [
        "I don't know.",
        "The document does not mention this.",
        "This is not specified in the provided context.",
        "There is insufficient information to answer this.",
    ],
)
def test_detects_hedge_phrases(answer):
    assert is_refusal(answer) is True


@pytest.mark.parametrize(
    "answer",
    [
        "The Harappan Civilization had the more advanced drainage system.",
        "40 patients.",
        "",
    ],
)
def test_confident_answers_are_not_refusals(answer):
    assert is_refusal(answer) is False


def test_case_insensitive():
    assert is_refusal("I DON'T KNOW.") is True
