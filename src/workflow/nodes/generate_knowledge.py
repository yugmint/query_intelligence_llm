import json

from src.processing.refusal_detector import is_refusal
from src.prompts.generation import build_generation_prompt

from src.workflow.resources import RAGResources
from src.workflow.state import RAGState

from src.utils.decorators import log_node
from src.utils.logger import logger


def _extract_answer(content: str) -> str:
    try:
        cleaned = content.replace("```json", "").replace("```", "").strip()
        parsed = json.loads(cleaned)
        return parsed.get("response", content)
    except Exception:
        logger.warning("Structured JSON response not received.")
        return content


@log_node("Generate_Knowledge")
def generate_knowledge_response(
    state: RAGState,
    resources: RAGResources,
):

    # ------------------------
    # Prepare
    # ------------------------

    logger.info("Building generation prompt.")

    prompt = build_generation_prompt(
        query=state["query"],
        context=state["context"],
        chat_history=state["chat_history"],
    )

    # ------------------------
    # Execute
    # ------------------------

    logger.info("Invoking LLM.")

    answer = _extract_answer(resources.llm.invoke(prompt).content)
    escalated = False

    # A refusal here doesn't always mean the answer isn't in the
    # context -- confirmed via a real test that the primary model
    # (llama-3.1-8b-instant) sometimes refuses comparative questions
    # ("which X had more/better Y") that a stronger model answers
    # correctly from the exact same retrieved context. One-shot retry
    # only, and only on refusal, to stay within the escalation model's
    # much tighter free-tier daily cap (see LLMFactory.get_escalation).
    if is_refusal(answer) and resources.escalation_llm is not None:
        logger.info("Primary answer looked like a refusal -- retrying with escalation LLM.")
        try:
            escalated_answer = _extract_answer(resources.escalation_llm.invoke(prompt).content)
            if not is_refusal(escalated_answer):
                answer = escalated_answer
                escalated = True
        except Exception:
            logger.warning("Escalation LLM call failed -- keeping the primary answer.")

    # ------------------------
    # Metrics
    # ------------------------

    logger.info(f"Generated Answer Length : {len(answer)}")

    # ------------------------
    # Return
    # ------------------------

    return {
        "answer": answer,
        "metadata": {
            **state.get("metadata", {}),
            "response_length": len(answer),
            "escalated": escalated,
        },
    }
