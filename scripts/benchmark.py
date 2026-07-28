#!/usr/bin/env python
"""
Automated retrieval + generation benchmark, against real indexes with
real questions -- replaces the ad-hoc manual spot-checking this project
relied on all session (grep the git history for "PRIOR:"/"NOW:" diffs
printed by one-off scripts). Ground truth below reuses question/answer/
source/page triples already hand-verified against real document text
earlier this session, not invented.

Two kinds of thing measured per question:

  Retrieval quality (from the raw ranked candidate list, before
  reranking trims it) -- Hit@1, Hit@3, Recall@5, MRR, Precision@5.
  Binary relevance only (a chunk counts as relevant iff it's on
  `expected_page` of `expected_source`) -- real nDCG needs graded
  relevance judgments this project doesn't have, and would collapse to
  the same signal Hit@K/MRR already give under binary relevance, so
  it's deliberately not implemented here.

  End-to-end answer quality (real RAGService.ask() call) --
  answer_correct (any of expected_answer_substring's keywords found,
  case-insensitive -- OR, for expect_refusal=True cases, whether the
  answer actually hedged), citation_correct (expected_page appears in
  the returned citations, or must_cite=True is satisfied by any
  citation at all), potential_hallucination (a confident, non-hedged
  answer that doesn't match -- a heuristic proxy via a phrase list,
  not an LLM-judged hallucination detector), and latency.

Also includes a graded subset of "Benchmark document for the history
book.docx" (an external benchmark spec, ~115 questions across 7
difficulty levels, received 2026-07-28): Level 5 "Synonyms" (5
questions) and Level 6 "Failure Tests" (10 questions) are the only
levels that state expected answers/behavior in that document, so
they're the only ones graded here. Levels 1-4 and the rest of Level 5
give question text only -- grading those needs the same real
hand-verification-against-the-source-PDF already done for every other
case in this file, not invented from the question alone.

Usage:
    python scripts/benchmark.py
"""

import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

CASES = [
    # Factor Analysis -- local/test_reports/factor_analysis_index
    dict(
        dataset="Factor Analysis",
        level="Manual Spot-Check",
        index_path="local/test_reports/factor_analysis_index",
        question="Who documented the scree graph?",
        expected_answer_substring="cattell",
        expected_source="Factor_Analysis.pdf",
        expected_page=3,
    ),
    dict(
        dataset="Factor Analysis",
        level="Manual Spot-Check",
        index_path="local/test_reports/factor_analysis_index",
        question="In Example 1, how many factors were retained, and what rotation was used?",
        expected_answer_substring="varimax",
        expected_source="Factor_Analysis.pdf",
        expected_page=None,  # not pinned down by hand this session -- answer-substring check only
    ),
    # EfficientNet -- local/test_reports/efficientnet_index
    dict(
        dataset="EfficientNet",
        level="Manual Spot-Check",
        index_path="local/test_reports/efficientnet_index",
        question="Where is the EfficientNet source code available?",
        expected_answer_substring="github.com/tensorflow/tpu",
        expected_source="EfficientNet.pdf",
        expected_page=None,
    ),
    dict(
        dataset="EfficientNet",
        level="Manual Spot-Check",
        index_path="local/test_reports/efficientnet_index",
        question="What accuracy does EfficientNet achieve on CIFAR-100 and Flowers in transfer learning?",
        expected_answer_substring="91.7",
        expected_source="EfficientNet.pdf",
        expected_page=None,
    ),
    # Airlock (COVID-19 severity study) -- local/test_reports/airlock_index
    dict(
        dataset="Airlock",
        level="Manual Spot-Check",
        index_path="local/test_reports/airlock_index",
        question="What was the sample size in this study?",
        expected_answer_substring="40 patients",
        expected_source=None,
        expected_page=None,
    ),
    # History book -- F:/.../ingestion_fixed/local/test_reports/history_book_index_v2
    dict(
        dataset="History Book",
        level="Manual Spot-Check",
        index_path=r"F:\Programming\RAG Projects\ingestion_fixed\local\test_reports\history_book_index_v2",
        question="Which schools of art were connected with Mahayana Buddhism?",
        expected_answer_substring="gandhara",
        expected_source="ede93-history.pdf",
        expected_page=41,
    ),
    dict(
        dataset="History Book",
        level="Manual Spot-Check",
        index_path=r"F:\Programming\RAG Projects\ingestion_fixed\local\test_reports\history_book_index_v2",
        question="What was the outcome of the 1971 Indo-Pak War?",
        expected_answer_substring="victory",
        expected_source="ede93-history.pdf",
        expected_page=101,
    ),
]

# ---------------------------------------------------------------------
# "Benchmark document for history book.docx" -- an external benchmark
# spec (~115 questions across 7 difficulty levels) received 2026-07-28.
# Only the two levels that actually carry stated expected answers/
# behavior in that document are included here as graded cases; Levels
# 1-4 (75 questions) and most of Level 5 give only the question text,
# no expected answer -- grading those needs the same real hand-
# verification-against-the-source-PDF this session already did for the
# CASES above, not invented from the question alone. Not done here;
# a separate task if wanted.
# ---------------------------------------------------------------------

_HISTORY_INDEX = r"F:\Programming\RAG Projects\ingestion_fixed\local\test_reports\history_book_index_v2"

CASES += [
    # Level 5 -- Retrieval Robustness / Synonyms subsection. The
    # benchmark doc states these five expected answers explicitly.
    dict(dataset="History Book", level="L5-Synonyms", index_path=_HISTORY_INDEX,
         question="Which civilization built excellent sewer systems?",
         expected_answer_substring=["harappan", "indus valley"], expected_source=None, expected_page=None),
    dict(dataset="History Book", level="L5-Synonyms", index_path=_HISTORY_INDEX,
         question="Who promoted moral governance?",
         expected_answer_substring="ashoka", expected_source=None, expected_page=None),
    dict(dataset="History Book", level="L5-Synonyms", index_path=_HISTORY_INDEX,
         question="Which empire first unified much of India?",
         expected_answer_substring="mauryan", expected_source=None, expected_page=None),
    dict(dataset="History Book", level="L5-Synonyms", index_path=_HISTORY_INDEX,
         question="Which civilization used bronze extensively?",
         # "harappan" alone false-negatived a real run: the model
         # correctly answered "Indus Valley Civilization" -- the same
         # entity, just the source's other name for it. Same fix would
         # apply to any other Harappan/Indus-Valley question here.
         expected_answer_substring=["harappan", "indus valley"],
         expected_source=None, expected_page=None),
    dict(dataset="History Book", level="L5-Synonyms", index_path=_HISTORY_INDEX,
         question="Which culture worshipped Proto-Shiva?",
         expected_answer_substring=["harappan", "indus valley"], expected_source=None, expected_page=None),

    # Level 6 -- Failure Tests. The benchmark doc states these should
    # NOT be answered confidently -- success here means a refusal/hedge,
    # the opposite polarity from every other case (expect_refusal=True).
    dict(dataset="History Book", level="L6-Failure Tests", index_path=_HISTORY_INDEX,
         question="Who was the last Harappan king?",
         expect_refusal=True, expected_source=None, expected_page=None),
    dict(dataset="History Book", level="L6-Failure Tests", index_path=_HISTORY_INDEX,
         question="Which language did Harappans speak?",
         expect_refusal=True, expected_source=None, expected_page=None),
    dict(dataset="History Book", level="L6-Failure Tests", index_path=_HISTORY_INDEX,
         question="What was Ashoka's favorite animal?",
         expect_refusal=True, expected_source=None, expected_page=None),
    dict(dataset="History Book", level="L6-Failure Tests", index_path=_HISTORY_INDEX,
         question="Give Harappan population figures.",
         expect_refusal=True, expected_source=None, expected_page=None),
    dict(dataset="History Book", level="L6-Failure Tests", index_path=_HISTORY_INDEX,
         question="What currency did Harappans use?",
         expect_refusal=True, expected_source=None, expected_page=None),
    dict(dataset="History Book", level="L6-Failure Tests", index_path=_HISTORY_INDEX,
         question="Who wrote the Harappan script?",
         expect_refusal=True, expected_source=None, expected_page=None),
    dict(dataset="History Book", level="L6-Failure Tests", index_path=_HISTORY_INDEX,
         question="What color were Harappan houses?",
         expect_refusal=True, expected_source=None, expected_page=None),
    dict(dataset="History Book", level="L6-Failure Tests", index_path=_HISTORY_INDEX,
         question="Which Mahajanapada had the largest army?",
         expect_refusal=True, expected_source=None, expected_page=None),
    dict(dataset="History Book", level="L6-Failure Tests", index_path=_HISTORY_INDEX,
         question="How many Harappan kings existed?",
         expect_refusal=True, expected_source=None, expected_page=None),
    dict(dataset="History Book", level="L6-Failure Tests", index_path=_HISTORY_INDEX,
         question="What was the exact cause of Harappan decline?",
         expect_refusal=True, expected_source=None, expected_page=None),
]

# ---------------------------------------------------------------------
# Levels 1-4 and the rest of Level 5, hand-verified against the real
# source PDF (the same standard as every other case in this file) --
# the benchmark doc gives question text only for these, no expected
# answers. L1 (exact fact) and most of L3/L5-remainder use tight
# keyword sets; L2 (multi-hop/compare) and L4 (long-context essay
# questions) are inherently fuzzier -- a real comparative/essay answer
# can be phrased many valid ways, so their keyword sets are
# deliberately looser topic anchors, a weaker correctness signal than
# L1's precise fact checks. Noted here, not hidden in the numbers.
# ---------------------------------------------------------------------

CASES += [
    # Level 1 -- Exact Fact Retrieval
    dict(dataset="History Book", level="L1-Exact Fact", index_path=_HISTORY_INDEX,
         question="What are the four main features of Indian culture?",
         expected_answer_substring=["continuity", "syncretism", "spirituality", "unity in diversity"],
         expected_source=None, expected_page=None),
    dict(dataset="History Book", level="L1-Exact Fact", index_path=_HISTORY_INDEX,
         question="What are the three dimensions of Indian heritage?",
         expected_answer_substring=["cultural", "historical", "natural"],
         expected_source=None, expected_page=None),
    dict(dataset="History Book", level="L1-Exact Fact", index_path=_HISTORY_INDEX,
         question="What are the major features of the Harappan drainage system?",
         expected_answer_substring=["drainage", "sewage", "soak-pit", "corbelled"],
         expected_source=None, expected_page=None),
    dict(dataset="History Book", level="L1-Exact Fact", index_path=_HISTORY_INDEX,
         question="What was the standard Harappan brick ratio?",
         expected_answer_substring="1:2:4", expected_source=None, expected_page=None),
    dict(dataset="History Book", level="L1-Exact Fact", index_path=_HISTORY_INDEX,
         question="Which Harappan site had the dockyard?",
         expected_answer_substring="lothal", expected_source=None, expected_page=None),
    dict(dataset="History Book", level="L1-Exact Fact", index_path=_HISTORY_INDEX,
         question="Which site contains the Great Bath?",
         # Real content gap, not a grading shortcut: this document
         # mentions "Great Bath" as an example but never states which
         # site it's at (unlike every other fact here). Answering
         # "Mohenjo-daro" would mean the model used outside/parametric
         # knowledge, not this document's retrieved context -- the
         # grounding-correct behavior is to decline, so this is graded
         # as a refusal case, same as Level 6.
         expect_refusal=True, expected_source=None, expected_page=None),
    dict(dataset="History Book", level="L1-Exact Fact", index_path=_HISTORY_INDEX,
         question="Where are the Bhimbetka rock shelters located?",
         expected_answer_substring="madhya pradesh", expected_source=None, expected_page=None),
    dict(dataset="History Book", level="L1-Exact Fact", index_path=_HISTORY_INDEX,
         question="Which Mahajanapada emerged as the most powerful?",
         expected_answer_substring="magadha", expected_source=None, expected_page=None),
    dict(dataset="History Book", level="L1-Exact Fact", index_path=_HISTORY_INDEX,
         question="Who were the rulers responsible for Magadha's rise?",
         expected_answer_substring=["bimbisara", "ajatashatru", "mahapadma nanda"],
         expected_source=None, expected_page=None),
    dict(dataset="History Book", level="L1-Exact Fact", index_path=_HISTORY_INDEX,
         question="Which crops were cultivated during the Harappan period?",
         expected_answer_substring=["wheat", "barley"], expected_source=None, expected_page=None),
    dict(dataset="History Book", level="L1-Exact Fact", index_path=_HISTORY_INDEX,
         question="What is NBPW?",
         expected_answer_substring="northern black polished ware", expected_source=None, expected_page=None),
    dict(dataset="History Book", level="L1-Exact Fact", index_path=_HISTORY_INDEX,
         question="What are Microliths?",
         expected_answer_substring=["small, pointed tools", "small pointed tools", "arrowheads"],
         expected_source=None, expected_page=None),
    dict(dataset="History Book", level="L1-Exact Fact", index_path=_HISTORY_INDEX,
         question="Name three important Neolithic sites.",
         expected_answer_substring=["mehrgarh", "burzahom", "chirand"],
         expected_source=None, expected_page=None),
    dict(dataset="History Book", level="L1-Exact Fact", index_path=_HISTORY_INDEX,
         question="Which civilization used the Proto-Shiva seal?",
         expected_answer_substring=["harappan", "indus valley"], expected_source=None, expected_page=None),
    dict(dataset="History Book", level="L1-Exact Fact", index_path=_HISTORY_INDEX,
         question="Which civilization had undeciphered logo-syllabic script?",
         expected_answer_substring=["harappan", "indus valley"], expected_source=None, expected_page=None),
    dict(dataset="History Book", level="L1-Exact Fact", index_path=_HISTORY_INDEX,
         question="What are the two parts of a Harappan city?",
         expected_answer_substring=["citadel", "lower town"], expected_source=None, expected_page=None),
    dict(dataset="History Book", level="L1-Exact Fact", index_path=_HISTORY_INDEX,
         question="Which period is called the Neolithic Revolution?",
         expected_answer_substring="neolithic", expected_source=None, expected_page=None),
    dict(dataset="History Book", level="L1-Exact Fact", index_path=_HISTORY_INDEX,
         question="What is Uttarapatha?",
         expected_answer_substring="trade route", expected_source=None, expected_page=None),
    dict(dataset="History Book", level="L1-Exact Fact", index_path=_HISTORY_INDEX,
         question="What is Dakshinapatha?",
         expected_answer_substring="trade route", expected_source=None, expected_page=None),
    dict(dataset="History Book", level="L1-Exact Fact", index_path=_HISTORY_INDEX,
         question="Which religion challenged Brahmanism during the Mahajanapada period?",
         expected_answer_substring=["buddhism", "jainism"], expected_source=None, expected_page=None),

    # Level 2 -- Multi-hop Retrieval (looser topic-anchor keywords -- see note above)
    dict(dataset="History Book", level="L2-Multi-hop", index_path=_HISTORY_INDEX,
         question="Compare Early Vedic and Later Vedic economies.",
         expected_answer_substring=["pastoral", "agricultur", "iron"], expected_source=None, expected_page=None),
    dict(dataset="History Book", level="L2-Multi-hop", index_path=_HISTORY_INDEX,
         question="How did geography influence Indian culture?",
         expected_answer_substring=["himalaya", "geograph"], expected_source=None, expected_page=None),
    dict(dataset="History Book", level="L2-Multi-hop", index_path=_HISTORY_INDEX,
         question="Explain why Magadha became powerful.",
         expected_answer_substring=["magadha", "iron", "fertile"], expected_source=None, expected_page=None),
    dict(dataset="History Book", level="L2-Multi-hop", index_path=_HISTORY_INDEX,
         question="How did the Second Urbanisation contribute to state formation?",
         expected_answer_substring=["mahajanapada", "urbanisation", "iron"], expected_source=None, expected_page=None),
    dict(dataset="History Book", level="L2-Multi-hop", index_path=_HISTORY_INDEX,
         question="Compare Harappan and Vedic societies.",
         expected_answer_substring=["harappan", "vedic"], expected_source=None, expected_page=None),
    dict(dataset="History Book", level="L2-Multi-hop", index_path=_HISTORY_INDEX,
         question="Explain continuity in Indian civilization.",
         expected_answer_substring=["continuity", "geograph", "caste"], expected_source=None, expected_page=None),
    dict(dataset="History Book", level="L2-Multi-hop", index_path=_HISTORY_INDEX,
         question="How did trade contribute to Harappan prosperity?",
         expected_answer_substring=["trade", "lothal", "seals"], expected_source=None, expected_page=None),
    dict(dataset="History Book", level="L2-Multi-hop", index_path=_HISTORY_INDEX,
         question="Compare Paleolithic and Neolithic lifestyles.",
         expected_answer_substring=["hunter-gatherer", "agricultur", "settled"], expected_source=None, expected_page=None),
    dict(dataset="History Book", level="L2-Multi-hop", index_path=_HISTORY_INDEX,
         question="Explain the relationship between agriculture and urbanization.",
         expected_answer_substring=["agricultural surplus", "urban"], expected_source=None, expected_page=None),
    dict(dataset="History Book", level="L2-Multi-hop", index_path=_HISTORY_INDEX,
         question="Compare monarchy and Ganasanghas.",
         expected_answer_substring=["monarch", "gana", "republic"], expected_source=None, expected_page=None),
    dict(dataset="History Book", level="L2-Multi-hop", index_path=_HISTORY_INDEX,
         question="Compare Harappan and Mauryan political organization.",
         expected_answer_substring=["centralized", "bureaucracy"], expected_source=None, expected_page=None),
    dict(dataset="History Book", level="L2-Multi-hop", index_path=_HISTORY_INDEX,
         question="Explain how geography influenced temple architecture.",
         expected_answer_substring=["nagara", "north"], expected_source=None, expected_page=None),
    dict(dataset="History Book", level="L2-Multi-hop", index_path=_HISTORY_INDEX,
         question="Compare Harappan religion and Vedic religion.",
         expected_answer_substring=["mother goddess", "indra", "agni", "proto-shiva"], expected_source=None, expected_page=None),
    dict(dataset="History Book", level="L2-Multi-hop", index_path=_HISTORY_INDEX,
         question="Explain how rivers shaped Indian civilization.",
         expected_answer_substring=["indus", "ganga", "river"], expected_source=None, expected_page=None),
    dict(dataset="History Book", level="L2-Multi-hop", index_path=_HISTORY_INDEX,
         question="Why is Bhimbetka important?",
         expected_answer_substring=["rock art", "prehistoric", "rock paintings"], expected_source=None, expected_page=None),
    dict(dataset="History Book", level="L2-Multi-hop", index_path=_HISTORY_INDEX,
         question="Compare Harappan art with Mauryan art.",
         expected_answer_substring=["seals", "pillars"], expected_source=None, expected_page=None),
    dict(dataset="History Book", level="L2-Multi-hop", index_path=_HISTORY_INDEX,
         question="Explain the role of trade routes.",
         expected_answer_substring=["uttarapatha", "dakshinapatha", "trade route"], expected_source=None, expected_page=None),
    dict(dataset="History Book", level="L2-Multi-hop", index_path=_HISTORY_INDEX,
         question="How did iron technology transform society?",
         expected_answer_substring=["iron", "agricultur", "surplus"], expected_source=None, expected_page=None),
    dict(dataset="History Book", level="L2-Multi-hop", index_path=_HISTORY_INDEX,
         question="Why is the Vedic period called foundational?",
         expected_answer_substring="foundational", expected_source=None, expected_page=None),
    dict(dataset="History Book", level="L2-Multi-hop", index_path=_HISTORY_INDEX,
         question="Compare Stone Age technology across all three phases.",
         expected_answer_substring=["hand axe", "microlith", "polished stone"], expected_source=None, expected_page=None),

    # Level 3 -- Semantic Retrieval ("intentionally avoid document wording")
    dict(dataset="History Book", level="L3-Semantic", index_path=_HISTORY_INDEX,
         question="Why was sanitation so advanced in Harappan cities?",
         expected_answer_substring=["drainage", "sewage"], expected_source=None, expected_page=None),
    dict(dataset="History Book", level="L3-Semantic", index_path=_HISTORY_INDEX,
         question="Which civilization demonstrated the earliest urban planning?",
         expected_answer_substring=["harappan", "indus valley"], expected_source=None, expected_page=None),
    dict(dataset="History Book", level="L3-Semantic", index_path=_HISTORY_INDEX,
         question="Which period marks the beginning of settled agriculture?",
         expected_answer_substring="neolithic", expected_source=None, expected_page=None),
    dict(dataset="History Book", level="L3-Semantic", index_path=_HISTORY_INDEX,
         question="How did climate affect civilization?",
         expected_answer_substring=["climate", "drought", "monsoon"], expected_source=None, expected_page=None),
    dict(dataset="History Book", level="L3-Semantic", index_path=_HISTORY_INDEX,
         question="Which civilization was the first large urban civilization in India?",
         expected_answer_substring=["harappan", "indus valley"], expected_source=None, expected_page=None),
    dict(dataset="History Book", level="L3-Semantic", index_path=_HISTORY_INDEX,
         question="Which ruler promoted Dhamma through inscriptions?",
         expected_answer_substring="ashoka", expected_source=None, expected_page=None),
    dict(dataset="History Book", level="L3-Semantic", index_path=_HISTORY_INDEX,
         question="Why were merchant classes important?",
         expected_answer_substring=["trade", "vaishya"], expected_source=None, expected_page=None),
    dict(dataset="History Book", level="L3-Semantic", index_path=_HISTORY_INDEX,
         question="Which civilization used standardized weights?",
         expected_answer_substring=["harappan", "indus valley"], expected_source=None, expected_page=None),
    dict(dataset="History Book", level="L3-Semantic", index_path=_HISTORY_INDEX,
         question="Which civilization depended heavily on maritime trade?",
         expected_answer_substring=["harappan", "indus valley", "chola"], expected_source=None, expected_page=None),
    dict(dataset="History Book", level="L3-Semantic", index_path=_HISTORY_INDEX,
         question="Why did Harappan cities disappear?",
         expected_answer_substring=["climate", "decline", "de-urbaniz"], expected_source=None, expected_page=None),

    # Level 4 -- Long-context Questions (broad essay-style topic anchors,
    # the loosest grading in this file -- see note above)
    dict(dataset="History Book", level="L4-Long-context", index_path=_HISTORY_INDEX,
         question="Explain the rise and decline of the Harappan Civilization.",
         expected_answer_substring=["harappan", "decline"], expected_source=None, expected_page=None),
    dict(dataset="History Book", level="L4-Long-context", index_path=_HISTORY_INDEX,
         question="Discuss continuity in Indian civilization.",
         expected_answer_substring="continuity", expected_source=None, expected_page=None),
    dict(dataset="History Book", level="L4-Long-context", index_path=_HISTORY_INDEX,
         question="Explain the evolution of Indian culture.",
         expected_answer_substring="culture", expected_source=None, expected_page=None),
    dict(dataset="History Book", level="L4-Long-context", index_path=_HISTORY_INDEX,
         question="Analyze the role of geography in Indian history.",
         expected_answer_substring="geograph", expected_source=None, expected_page=None),
    dict(dataset="History Book", level="L4-Long-context", index_path=_HISTORY_INDEX,
         question="Explain the transition from Stone Age to Vedic society.",
         expected_answer_substring=["stone age", "vedic"], expected_source=None, expected_page=None),
    dict(dataset="History Book", level="L4-Long-context", index_path=_HISTORY_INDEX,
         question="Discuss the importance of art in understanding history.",
         expected_answer_substring="art", expected_source=None, expected_page=None),
    dict(dataset="History Book", level="L4-Long-context", index_path=_HISTORY_INDEX,
         question="Explain the Second Urbanisation.",
         expected_answer_substring=["second urbanisation", "mahajanapada"], expected_source=None, expected_page=None),
    dict(dataset="History Book", level="L4-Long-context", index_path=_HISTORY_INDEX,
         question="Evaluate the significance of the Mahajanapadas.",
         expected_answer_substring="mahajanapada", expected_source=None, expected_page=None),
    dict(dataset="History Book", level="L4-Long-context", index_path=_HISTORY_INDEX,
         question="Explain the evolution of Indian philosophy.",
         expected_answer_substring=["orthodox", "heterodox", "buddhis"], expected_source=None, expected_page=None),
    dict(dataset="History Book", level="L4-Long-context", index_path=_HISTORY_INDEX,
         question="Compare all major ancient civilizations covered.",
         expected_answer_substring=["harappan", "vedic", "mauryan"], expected_source=None, expected_page=None),

    # Level 5 -- Retrieval Robustness: Indirect wording
    dict(dataset="History Book", level="L5-Indirect", index_path=_HISTORY_INDEX,
         question="Which civilization had no deciphered writing?",
         expected_answer_substring=["harappan", "indus valley"], expected_source=None, expected_page=None),
    dict(dataset="History Book", level="L5-Indirect", index_path=_HISTORY_INDEX,
         question="Which period saw agriculture replace hunting?",
         expected_answer_substring="neolithic", expected_source=None, expected_page=None),
    dict(dataset="History Book", level="L5-Indirect", index_path=_HISTORY_INDEX,
         question="Which kingdom benefited from fertile Gangetic plains?",
         expected_answer_substring="magadha", expected_source=None, expected_page=None),
    dict(dataset="History Book", level="L5-Indirect", index_path=_HISTORY_INDEX,
         question="Which movement challenged ritualism?",
         expected_answer_substring=["buddhis", "jainis", "heterodox"], expected_source=None, expected_page=None),
    dict(dataset="History Book", level="L5-Indirect", index_path=_HISTORY_INDEX,
         question="Which civilization built cities using standardized bricks?",
         expected_answer_substring=["harappan", "indus valley"], expected_source=None, expected_page=None),

    # Level 5 -- Retrieval Robustness: Ambiguous wording (loosest grading
    # in this level -- deliberately vague questions, broad topic anchors)
    dict(dataset="History Book", level="L5-Ambiguous", index_path=_HISTORY_INDEX,
         question="Tell me about ancient trade.",
         expected_answer_substring="trade", expected_source=None, expected_page=None),
    dict(dataset="History Book", level="L5-Ambiguous", index_path=_HISTORY_INDEX,
         question="Explain India's earliest cities.",
         expected_answer_substring=["harappan", "indus valley"], expected_source=None, expected_page=None),
    dict(dataset="History Book", level="L5-Ambiguous", index_path=_HISTORY_INDEX,
         question="How did people worship?",
         expected_answer_substring=["worship", "religio"], expected_source=None, expected_page=None),
    dict(dataset="History Book", level="L5-Ambiguous", index_path=_HISTORY_INDEX,
         question="How did technology evolve?",
         expected_answer_substring=["technolog", "iron", "tool"], expected_source=None, expected_page=None),
    dict(dataset="History Book", level="L5-Ambiguous", index_path=_HISTORY_INDEX,
         question="Tell me about political systems.",
         expected_answer_substring=["monarch", "republic", "mahajanapada"], expected_source=None, expected_page=None),

    # Level 5 -- Retrieval Robustness: Cross-document style (comparative
    # across periods/civilizations covered in different sections)
    dict(dataset="History Book", level="L5-Cross-document", index_path=_HISTORY_INDEX,
         question="Which civilization had the better drainage system?",
         expected_answer_substring=["harappan", "indus valley"], expected_source=None, expected_page=None),
    dict(dataset="History Book", level="L5-Cross-document", index_path=_HISTORY_INDEX,
         question="Which era gave women greater freedom?",
         expected_answer_substring=["early vedic", "early-vedic"], expected_source=None, expected_page=None),
    dict(dataset="History Book", level="L5-Cross-document", index_path=_HISTORY_INDEX,
         question="Which civilization had better trade networks?",
         expected_answer_substring=["harappan", "indus valley", "chola"], expected_source=None, expected_page=None),
    dict(dataset="History Book", level="L5-Cross-document", index_path=_HISTORY_INDEX,
         question="Which period had the greatest technological leap?",
         expected_answer_substring=["neolithic", "iron"], expected_source=None, expected_page=None),
    dict(dataset="History Book", level="L5-Cross-document", index_path=_HISTORY_INDEX,
         question="Which civilization left undeciphered inscriptions?",
         expected_answer_substring=["harappan", "indus valley"], expected_source=None, expected_page=None),
]

for _case in CASES:
    _case.setdefault("level", "Manual Spot-Check")
    _case.setdefault("must_cite", False)
    _case.setdefault("expect_refusal", False)


def _is_relevant(document, expected_source, expected_page) -> bool:
    if expected_page is None:
        return False  # can't judge retrieval-rank relevance without a page to match
    meta = document.metadata
    if expected_source and meta.get("source") != expected_source:
        return False
    return meta.get("page_number") == expected_page


def retrieval_metrics(vectorstore, query, expected_source, expected_page, k=15):
    if expected_page is None:
        return None

    ranked = vectorstore.similarity_search(query, k=k)
    relevant_ranks = [
        i + 1 for i, d in enumerate(ranked) if _is_relevant(d, expected_source, expected_page)
    ]

    return {
        "hit@1": len(relevant_ranks) > 0 and relevant_ranks[0] == 1,
        "hit@3": any(r <= 3 for r in relevant_ranks),
        "recall@5": any(r <= 5 for r in relevant_ranks),
        "mrr": (1.0 / relevant_ranks[0]) if relevant_ranks else 0.0,
        "precision@5": sum(1 for r in relevant_ranks if r <= 5) / 5,
    }


# Broader than a literal "i don't know" -- Level 6 "Failure Tests" cases
# (scripts/benchmark.py CASES, is_refusal=True) expect a hedge/refusal
# phrased any number of ways ("not mentioned", "the document does not
# specify", "no information about", etc.), not that one exact sentence.
_REFUSAL_PHRASES = [
    "i don't know",
    "not mentioned",
    "not specified",
    "not available",
    "not stated",
    "not provided",
    "no information",
    "does not mention",
    "does not specify",
    "does not provide",
    "does not state",
    "unclear from",
    "cannot determine",
    "unable to determine",
    "insufficient information",
    "no mention of",
    "the document does not",
    "not indicate",
]


def _is_refusal(answer_lower: str) -> bool:
    return any(phrase in answer_lower for phrase in _REFUSAL_PHRASES)


def generation_metrics(rag_service, case):
    start = time.perf_counter()
    state = rag_service.ask(case["question"], session_id=f"bench-{hash(case['question'])}", return_state=True)
    latency = time.perf_counter() - start

    answer = state["answer"]
    answer_lower = answer.lower()
    is_refusal = _is_refusal(answer_lower)

    if case.get("expect_refusal"):
        # Level 6 "Failure Tests": success means the system correctly
        # declined rather than confidently answering with something
        # unsupported -- the opposite polarity from every other case.
        answer_correct = is_refusal
        potential_hallucination = not is_refusal
    else:
        keywords = case["expected_answer_substring"]
        if isinstance(keywords, str):
            keywords = [keywords]
        answer_correct = any(kw.lower() in answer_lower for kw in keywords)
        potential_hallucination = (not answer_correct) and (not is_refusal)

    citation_correct = None
    if case.get("expected_page") is not None:
        citation_correct = any(
            c.get("page") == case["expected_page"]
            and (case["expected_source"] is None or c.get("source") == case["expected_source"])
            for c in state["citations"]
        )
    elif case.get("must_cite"):
        citation_correct = len(state["citations"]) > 0

    return {
        "answer_correct": answer_correct,
        "potential_hallucination": potential_hallucination,
        "citation_correct": citation_correct,
        "latency": latency,
    }


def _pct(values):
    values = [v for v in values if v is not None]
    return 100 * sum(1 for v in values if v) / len(values) if values else float("nan")


def _mean(values):
    values = [v for v in values if v is not None]
    return statistics.mean(values) if values else float("nan")


def _build_rag_service(index_path, embeddings, reranker, llm):
    """
    RAGService normally builds its own resources via build_resources(),
    which reads FAISS_INDEX_PATH once at *import* time (a `from ... import
    FAISS_PATH` binding in vectorstore.py) -- setting the env var again
    mid-process, to switch between this script's several datasets, would
    silently do nothing (a real bug hit and root-caused earlier this
    session running ad-hoc multi-dataset comparison scripts the same way).
    Sidesteps it entirely: build RAGResources directly from an explicitly
    loaded vectorstore, and monkeypatch build_resources for just this one
    RAGService() construction -- the same technique tests/test_rag_service_*
    already use to inject fake resources.
    """
    import src.services.rag_service as rag_service_module
    from src.retrieval.bm25 import BM25Factory
    from src.retrieval.retriever import RetrieverFactory
    from src.workflow.resources import RAGResources
    from langchain_community.vectorstores import FAISS

    vectorstore = FAISS.load_local(index_path, embeddings, allow_dangerous_deserialization=True)
    resources = RAGResources(
        llm=llm,
        embeddings=embeddings,
        vectorstore=vectorstore,
        retriever=RetrieverFactory.build(vectorstore),
        reranker=reranker,
        bm25_retriever=BM25Factory.build(vectorstore),
    )

    original_build_resources = rag_service_module.build_resources
    rag_service_module.build_resources = lambda: resources
    try:
        service = rag_service_module.RAGService()
    finally:
        rag_service_module.build_resources = original_build_resources

    return service, vectorstore


def main():
    from src.retrieval.embeddings import EmbeddingFactory
    from src.retrieval.llm import LLMFactory
    from src.retrieval.reranker import RerankerFactory

    embeddings = EmbeddingFactory.get()
    reranker = RerankerFactory.get()
    llm = LLMFactory.get()

    results = []
    for case in CASES:
        index_path = case["index_path"]
        if not Path(index_path).exists():
            print(f"SKIP  {case['dataset']!r} / {case['question']!r} -- index not found at {index_path}")
            continue

        rag_service, vectorstore = _build_rag_service(index_path, embeddings, reranker, llm)

        r = retrieval_metrics(vectorstore, case["question"], case["expected_source"], case["expected_page"])
        g = generation_metrics(rag_service, case)

        results.append({**case, "retrieval": r, "generation": g})

        label = "refusal_correct" if case["expect_refusal"] else "answer_correct"
        print(f"[{case['level']:<16}] {case['question'][:55]:<55} "
              f"{label}={g['answer_correct']!s:<5} "
              f"latency={g['latency']:.2f}s")

    def _report(label, rows):
        gen = [r["generation"] for r in rows]
        ret = [r["retrieval"] for r in rows if r["retrieval"] is not None]

        print()
        print("=" * 78)
        print(label)
        print("=" * 78)
        print(f"Questions run:            {len(rows)}")
        print(f"Answer correctness:       {_pct([g['answer_correct'] for g in gen]):.0f}%")
        print(f"Potential hallucination:  {_pct([g['potential_hallucination'] for g in gen]):.0f}%  (heuristic proxy, see module docstring)")
        judgeable = sum(1 for g in gen if g['citation_correct'] is not None)
        print(f"Citation accuracy:        {_pct([g['citation_correct'] for g in gen]):.0f}%  (of {judgeable} judgeable)")
        print(f"Mean latency:             {_mean([g['latency'] for g in gen]):.2f}s  (target from the benchmark doc: <2s)")
        if ret:
            print(f"Retrieval Hit@1:          {_pct([r['hit@1'] for r in ret]):.0f}%  (of {len(ret)} judgeable)")
            print(f"Retrieval Hit@3:          {_pct([r['hit@3'] for r in ret]):.0f}%")
            print(f"Retrieval Recall@5:       {_pct([r['recall@5'] for r in ret]):.0f}%")
            print(f"Retrieval MRR:            {_mean([r['mrr'] for r in ret]):.2f}")
            print(f"Retrieval Precision@5:    {_mean([r['precision@5'] for r in ret]):.2f}")

    levels = sorted({r["level"] for r in results})
    for level in levels:
        _report(f"LEVEL: {level}", [r for r in results if r["level"] == level])

    _report("OVERALL", results)

    print()
    print("Note: 'Confidence Score' (a target metric in the benchmark doc's")
    print("Production Benchmark table) is not implemented -- deliberately")
    print("skipped, see docs/05-roadmap.md v0.5.0 'confidence calibration'.")


if __name__ == "__main__":
    main()
