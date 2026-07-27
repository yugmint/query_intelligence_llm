"""
Tests for src/processing/numeric_question.py::is_numeric_question.
"""

import pytest

from src.processing.numeric_question import is_numeric_question


@pytest.mark.parametrize(
    "query",
    [
        "What was the sample size in this study?",
        "What was the sample size?",
        "How many patients were enrolled in the study?",
        "How much did the treatment cost?",
        "How long did the trial last?",
        "How old were the participants on average?",
        "What percentage of patients were male?",
        "What proportion of the cohort was severe?",
        "What is the total number of citations?",
        "What was the dosage used?",
        "How often was the drug administered?",
    ],
)
def test_detects_numeric_questions(query):
    assert is_numeric_question(query) is True


@pytest.mark.parametrize(
    "query",
    [
        "What is factor analysis?",
        "Summarize the methodology used in this paper.",
        "Who are the authors of this document?",
        "What imaging modality was used?",
        "What is this document about?",
        "Explain the proposed model in detail.",
    ],
)
def test_does_not_flag_non_numeric_questions(query):
    assert is_numeric_question(query) is False


def test_case_insensitive():
    assert is_numeric_question("HOW MANY PATIENTS WERE ENROLLED?") is True
