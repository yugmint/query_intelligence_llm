# src/retrieval/llm.py

import os
import json
from typing import Optional

from langchain_groq import ChatGroq
from langchain_core.rate_limiters import InMemoryRateLimiter

from src.retrieval.config import MODEL_NAME


class LLMFactory:
    """Factory for LLM client instances."""

    _instance: Optional[any] = None
    _escalation_instance: Optional[any] = None

    @staticmethod
    def _load_api_key():
        if os.environ.get("GROQ_API_KEY"):
            return

        with open("cred.json") as f:
            data = json.load(f)
            os.environ["GROQ_API_KEY"] = data["grok_api_key"]

    @classmethod
    def get(cls):

        if cls._instance is None:

            cls._load_api_key()

            # Groq's free tier for this model caps at 6,000 tokens/minute --
            # confirmed by an actual crash under 5 concurrent requests
            # (each knowledge query makes 2 calls through this one shared
            # instance -- intent classification + generation -- at roughly
            # 900-1100 tokens each, so ~3 concurrent knowledge queries/min
            # is the real sustainable ceiling). Considered switching
            # providers for more headroom (Cerebras: blocked on account
            # billing status; Google Gemini: free tier may use traffic to
            # improve their products, unacceptable for this public-facing
            # service) -- Groq is explicitly *not* permitted to train on
            # API inputs/outputs without opt-in (SOC 2 Type II, see Groq's
            # Trust Center), so it's also the most privacy-safe of the
            # three, not just the path of least resistance. See
            # docs/reports/2026-07-26-performance-and-deployment-readiness.md.
            #
            # Proactively throttling client-side (rather than only
            # reacting to 429s after the fact) turns a burst of concurrent
            # queries into a brief queue instead of a hard failure.
            # max_bucket_size=2 lets one query's own 2 calls (intent +
            # generation) go through back-to-back without an artificial
            # gap between them; requests_per_second is tuned so the
            # *sustained* rate stays safely under the 6,000 TPM ceiling
            # (0.08/sec = 4.8 calls/min =~ 4800 tokens/min budget at
            # ~1000 tokens/call, leaving headroom for larger-than-average
            # contexts) rather than riding the exact limit.
            rate_limiter = InMemoryRateLimiter(
                requests_per_second=0.08,
                check_every_n_seconds=0.1,
                max_bucket_size=2,
            )

            cls._instance = ChatGroq(
                model=MODEL_NAME,
                rate_limiter=rate_limiter,
                max_retries=3,
                request_timeout=30,
            )

        return cls._instance

    @classmethod
    def build(cls):
        return cls.get()

    @classmethod
    def get_escalation(cls):
        """
        A stronger model (openai/gpt-oss-20b, MoE -- reasoning quality
        closer to a much larger dense model at a fraction of the
        per-token compute) used ONLY as a one-shot retry when the
        primary model (llama-3.1-8b-instant) refuses to answer a
        comparative question it actually had the context for --
        confirmed via a real test (drainage-system/trade-network/
        technological-leap questions): 0/4 answered by the primary
        model, 2/4 answered correctly by this one on the exact same
        retrieved context. See docs/05-roadmap.md.

        Free tier caps this model at 1,000 requests/day (vs. 14,400/day
        for the primary) -- see the same roadmap entry for why that
        ruled out making it the default. No daily-cap tracking here
        (ponytail: this is a rare retry-only path, not the hot path;
        add real usage accounting if this ever gets close to that
        ceiling) -- Groq just returns 429s past it, which the retry
        call's own max_retries/timeout already surfaces as a normal
        failure, not a crash.
        """

        if cls._escalation_instance is None:

            cls._load_api_key()

            rate_limiter = InMemoryRateLimiter(
                requests_per_second=0.1,
                check_every_n_seconds=0.1,
                max_bucket_size=1,
            )

            cls._escalation_instance = ChatGroq(
                model="openai/gpt-oss-20b",
                rate_limiter=rate_limiter,
                max_retries=2,
                request_timeout=30,
            )

        return cls._escalation_instance