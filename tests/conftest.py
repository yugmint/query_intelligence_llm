"""
Shared test fixtures/fakes for workflow node unit tests.

Nodes take (state, resources) and call out to resources.llm / .retriever --
these fakes stand in for both without any real network/API/FAISS call, so
node tests stay fast and deterministic.
"""

from types import SimpleNamespace

import pytest

from src.workflow.resources import RAGResources


class FakeLLM:
    """
    Stand-in for resources.llm. Records every prompt it's asked to invoke
    and returns a scripted response -- a fixed string, a list consumed one
    per call (last one repeats once exhausted), or an Exception instance
    to simulate an LLM/parsing failure path.
    """

    def __init__(self, responses):
        self._responses = list(responses) if isinstance(responses, (list, tuple)) else [responses]
        self.prompts: list[str] = []
        self.call_count = 0

    def invoke(self, prompt: str):
        self.prompts.append(prompt)
        index = min(self.call_count, len(self._responses) - 1)
        response = self._responses[index]
        self.call_count += 1

        if isinstance(response, Exception):
            raise response

        return SimpleNamespace(content=response)


class FakeRetriever:
    """Stand-in for resources.retriever. Records the query it was asked."""

    def __init__(self, documents):
        self._documents = documents
        self.queries: list[str] = []

    def invoke(self, query: str):
        self.queries.append(query)
        return self._documents


class FakeReranker:
    """
    Stand-in for resources.reranker (a sentence_transformers.CrossEncoder
    in production). Records every batch of (query, chunk) pairs it's
    asked to score and returns scripted scores -- one list of scores per
    call to .predict(), matching CrossEncoder's real signature/return
    shape (a list of floats, same order as the input pairs).
    """

    def __init__(self, scores):
        self._scores = list(scores) if isinstance(scores[0], (list, tuple)) else [scores]
        self.calls: list[list[tuple[str, str]]] = []
        self.call_count = 0

    def predict(self, pairs):
        self.calls.append(list(pairs))
        index = min(self.call_count, len(self._scores) - 1)
        scores = self._scores[index]
        self.call_count += 1
        return scores


class FakeVectorStore:
    """
    Stand-in for resources.vectorstore -- specifically its
    .similarity_search(query, k, filter=...) method, the direct-vectorstore
    fallback path retrieve_documents() uses when a metadata_filter is
    present (VectorStoreRetriever has no way to accept a per-query filter
    override). Records every call's args and returns a scripted list of
    documents, ignoring the filter itself -- the node's job is just to
    pass it through correctly, not to actually filter.
    """

    def __init__(self, documents):
        self._documents = documents
        self.calls: list[dict] = []

    def similarity_search(self, query: str, k=None, filter=None):
        self.calls.append({"query": query, "k": k, "filter": filter})
        return self._documents


def make_resources(
    llm=None, retriever=None, reranker=None, vectorstore=None, bm25_retriever=None
) -> RAGResources:
    """
    Build a RAGResources with only the fields a given node actually uses
    populated -- the rest are None, which is fine since nothing in these
    tests touches them.
    """
    return RAGResources(
        llm=llm,
        embeddings=None,
        vectorstore=vectorstore,
        retriever=retriever,
        reranker=reranker,
        bm25_retriever=bm25_retriever,
    )


@pytest.fixture(autouse=True)
def _reset_query_rewriter_singleton():
    """
    QueryRewriter (src/processing/query_rewriter.py) caches itself as a
    class-level singleton keyed on nothing -- the first `.get(resources)`
    call wins for the rest of the process. Without resetting this between
    tests, a FakeLLM from one test would leak into every later test that
    touches process_query. Autouse so every test file gets this for free.
    """
    from src.processing.query_rewriter import QueryRewriter

    QueryRewriter._instance = None
    yield
    QueryRewriter._instance = None
