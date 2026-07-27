from src.workflow.state import RAGState
from src.workflow.resources import RAGResources

from src.utils.decorators import log_node
from src.utils.logger import logger


@log_node("Generate_Conversation")
def generate_conversation(
    state: RAGState,
    resources: RAGResources,
):
    """
    Plain-text response, deliberately -- not JSON-wrapped like an
    earlier version of this node asked for. Two reasons: (1) streaming
    (RAGService.ask_stream()) forwards this node's raw LLM output
    token-by-token; a JSON-wrapped response would show the user a
    literal `{`, `"response": "`, etc. typing itself out instead of
    clean conversational text. (2) generate_knowledge.py already
    demonstrates the same JSON-wrapper instruction doesn't reliably get
    honored in practice (logs "Structured JSON response not received"
    on nearly every real call) -- nothing was actually depending on
    structured output here either, just the extracted text.
    """

    logger.info(
        f"Conversation Intent : {state['intent']}"
    )

    prompt = f"""
You are a friendly AI assistant.

Respond naturally, in plain text. Do not use markdown code fences or
JSON -- just the response itself.

Current intent:
{state["intent"]}

Conversation History:
{state["chat_history"]}

User:
{state["query"]}
"""

    response = resources.llm.invoke(prompt)

    return {

        "answer": response.content.strip(),

        "metadata": {

            **state.get("metadata", {}),

            "intent": state["intent"],

        }

    }