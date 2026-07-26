# src/processing/query_rewriter.py

import json
import re
from typing import Optional

from src.workflow.resources import RAGResources
from src.utils.logger import logger

# Words that typically signal an unresolved reference to prior context.
# If none of these appear AND there's no chat history, we skip the LLM
# call entirely and just use the original query.
_PRONOUN_TRIGGERS = {
    "it", "this", "that", "they", "them", "those", "these", "he", "she",
    "him", "her", "his", "its", "their"
}


class QueryRewriter:
    """
    Singleton responsible for rewriting user queries into
    retrieval-friendly search queries.

    Found and fixed 2026-07-26 via real multi-turn use through the local
    frontend: a bare "resolve pronouns using history" instruction isn't
    enough once more than one topic has been discussed -- given history
    that first covered a paper's improvements broadly, then specifically
    defined "spatial pyramid pooling", the query "detailed intuition of
    it" got rewritten to "intuition of the proposed model" (the earlier,
    more-discussed topic) instead of "intuition of spatial pyramid
    pooling" (what was actually named last). Fixed by adding an explicit
    recency-priority rule and a matching example to the prompt below.
    Reproduced directly against the real LLM (not just unit tests with a
    fake) before and after; 3/3 consistent after the fix. See
    docs/06-release-notes.md.
    """
    _instance: Optional['QueryRewriter'] = None

    def __init__(self, resources: RAGResources):
        self.resources = resources
        self.llm = resources.llm

    @classmethod
    def get(
        cls,
        resources: RAGResources
    ):
        if cls._instance is None:

            logger.info("=" * 80)
            logger.info("Initializing Query Rewriter")

            cls._instance = QueryRewriter(resources)

            logger.info("Query Rewriter initialized successfully.")
        else:
            logger.debug("Reusing existing Query Rewriter instance.")

        return cls._instance

    @staticmethod
    def _needs_rewrite(query: str, chat_history: str) -> bool:
        """
        Cheap heuristic to decide whether an LLM rewrite is worth doing.

        We only bother calling the LLM when there IS conversation
        history AND the query contains a pronoun/reference that could
        plausibly need resolving. This avoids burning a full LLM
        round-trip on queries that are already retrieval-ready
        (e.g. "Explain Kubernetes.").
        """
        if not chat_history or not chat_history.strip():
            return False

        tokens = set(re.findall(r"[a-zA-Z']+", query.lower()))
        return bool(tokens & _PRONOUN_TRIGGERS)

    @staticmethod
    def _extract_json(content: str) -> dict:
        """
        Extracts the first JSON object found in the LLM's response,
        tolerant of markdown fences or stray text around it.
        """
        cleaned = (
            content
            .replace("```json", "")
            .replace("```", "")
            .strip()
        )

        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not match:
            raise ValueError("No JSON object found in response")

        return json.loads(match.group(0))

    def rewrite(
        self, query: str,
        chat_history: str = ""
    ) -> str:
        """
        Rewrites the user query into a short, retrieval-friendly
        search query, resolving references from chat history.

        Parameters
        ----------
        query : str
            The original user query.

        chat_history : str
            The conversation history.

        Returns
        -------
        str
            The rewritten query, or the original query if rewriting
            is skipped or fails.
        """

        logger.info(f"Rewriting Query : {query}")

        if not self._needs_rewrite(query, chat_history):
            logger.info(
                "Skipping rewrite (no chat history or no references "
                "to resolve)."
            )
            return query

        prompt = f"""
You are a Query Rewriter for a retrieval system (RAG). Your only job is
to rewrite the user's query into a short, keyword-rich SEARCH QUERY —
not a sentence, not a request, not an answer.

Rules:
- Resolve pronouns and references (it, this, that, they, those, etc.)
  using the conversation history below.
- When more than one thing has been discussed, resolve the pronoun to
  the MOST RECENTLY mentioned specific noun/topic -- the last thing
  actually named -- not an earlier, broader, or more general one, even
  if that earlier topic was discussed at greater length. Recency beats
  salience: prefer "the last thing named" over "the main thing this
  conversation has been about."
- Do NOT invent facts that aren't in the history.
- Do NOT answer the question.
- Do NOT phrase it as a request or instruction (e.g. never write
  "Please provide..." or "Explain...").
- Keep it short: a noun phrase or keyword string, max ~12 words.
- If the query is already clear and self-contained, return it unchanged.

Examples:

History: User previously asked about the "Deep Learning" book.
Query: "Who wrote it?"
Output: {{"rewritten_query": "Author of the Deep Learning book"}}

History: (empty)
Query: "Summarize this book."
Output: {{"rewritten_query": "Summary of the book"}}

History: User previously asked about onboarding steps for new hires.
Query: "What about the second one?"
Output: {{"rewritten_query": "Second onboarding step for new hires"}}

History: User asked for an overview of a paper and got a broad answer
about its general improvements. Then, in the very next turn, user
asked specifically "What is spatial pyramid pooling?" and got a
definition of it.
Query: "Give me detailed intuition of it"
Output: {{"rewritten_query": "Detailed intuition of spatial pyramid pooling"}}
(Not "detailed intuition of the paper's improvements" -- that was the
earlier, broader topic; spatial pyramid pooling is what was actually
named last.)

Return ONLY valid JSON in this exact shape, with no extra text and no
markdown fences:

{{"rewritten_query": "<rewritten query>"}}

Conversation History:
{chat_history}

User Query:
{query}
"""

        logger.info("Rewriting user query.")

        response = self.llm.invoke(prompt)

        try:
            parsed = self._extract_json(response.content)
            rewritten = parsed["rewritten_query"].strip()

            if not rewritten:
                raise ValueError("Empty rewritten_query")

            logger.info(f"Original Query  : {query}")
            logger.info(f"Rewritten Query : {rewritten}")

            return rewritten

        except Exception as e:
            logger.warning(
                f"Query rewriting failed ({e}). "
                f"Raw response: {response.content!r}. "
                "Using original query."
            )
            return query