from src.processing.intent_classifier import classify_intent
from src.workflow.resources import RAGResources
from src.workflow.state import RAGState

from src.utils.decorators import log_node
from src.utils.logger import logger


@log_node("Intent")
def detect_intent(
    state: RAGState,
    resources: RAGResources,
):
    """
    No LLM call -- see src/processing/intent_classifier.py for why.
    `resources` is still accepted (unused) to keep this node's call
    signature uniform with every other node in workflow.py.
    """

    # ------------------------
    # Prepare
    # ------------------------

    query = state["query"]

    logger.info(f"Processing Query : {query}")

    # ------------------------
    # Execute
    # ------------------------

    intent = classify_intent(query)

    # ------------------------
    # Metrics
    # ------------------------

    logger.info(f"Detected Intent : {intent}")

    # ------------------------
    # Return
    # ------------------------

    return {
        "intent": intent,
        "metadata": {
            **state.get("metadata", {}),
            "intent": intent,
        },
    }
