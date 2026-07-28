import json

from src.processing.refusal_detector import is_refusal
from src.prompts.generation import build_generation_prompt

from src.workflow.resources import RAGResources
from src.workflow.state import RAGState

from src.utils.decorators import log_node
from src.utils.logger import logger
from src.utils.metrics import QUERY_COST_USD_TOTAL
from src.utils.pricing import estimate_cost_usd


def _extract_answer(content: str) -> str:
    try:
        cleaned = content.replace("```json", "").replace("```", "").strip()
        parsed = json.loads(cleaned)
        return parsed.get("response", content)
    except Exception:
        logger.warning("Structured JSON response not received.")
        return content


def _response_cost_usd(response) -> float:
    usage = getattr(response, "usage_metadata", None) or {}
    response_metadata = getattr(response, "response_metadata", None) or {}
    model_name = response_metadata.get("model_name")
    if not usage or not model_name:
        return 0.0
    cost = estimate_cost_usd(model_name, usage.get("input_tokens", 0), usage.get("output_tokens", 0))
    return cost if cost is not None else 0.0


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

    primary_response = resources.llm.invoke(prompt)
    answer = _extract_answer(primary_response.content)
    cost_usd = _response_cost_usd(primary_response)
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
            escalation_response = resources.escalation_llm.invoke(prompt)
            cost_usd += _response_cost_usd(escalation_response)
            escalated_answer = _extract_answer(escalation_response.content)
            if not is_refusal(escalated_answer):
                answer = escalated_answer
                escalated = True
        except Exception:
            logger.warning("Escalation LLM call failed -- keeping the primary answer.")

    QUERY_COST_USD_TOTAL.inc(cost_usd)

    # ------------------------
    # Metrics
    # ------------------------

    logger.info(f"Generated Answer Length : {len(answer)}")
    logger.info(f"Estimated Cost (USD) : {cost_usd:.6f}")

    # ------------------------
    # Return
    # ------------------------

    return {
        "answer": answer,
        "metadata": {
            **state.get("metadata", {}),
            "response_length": len(answer),
            "escalated": escalated,
            "cost_usd": cost_usd,
        },
    }
