"""Embeddings: turning text into vectors of meaning.

An embedding is a list of numbers (ours are 1536 long) representing what
a text is ABOUT, such that texts about similar things get nearby vectors.
That single property powers stage one of matching: "find the 25 postings
whose vectors sit closest to this resume's vector" is one fast database
query over thousands of rows — no AI reading required, almost no cost.

The rules of this module are the gateway's rules, applied to a second
paid service:

1. Instrumented: every embedding call is recorded in agent_runs (agent
   "embedder"), with tokens and dollars. Paid calls are never invisible.
2. Fake mode obeys the same switch (FAKE_AI) — but with a twist worth
   understanding: fake embeddings here are NOT random numbers. They are
   word-overlap vectors ("feature hashing": every word votes into a slot
   chosen by its hash, then the vector is normalized). Texts sharing
   words genuinely land near each other, so in free fake mode the whole
   matching machinery still ranks plausibly — you can watch it work
   before spending a cent. What fake mode lacks is UNDERSTANDING:
   "ML engineer" and "machine learning engineer" share little text but
   mean the same thing; only real embeddings know that. Mechanics for
   free, intelligence when you switch.
"""

import hashlib
import math
import time

from openai import AsyncOpenAI

from app.config import settings
from app.llm import estimate_cost_usd, record_run


def fake_embedding(text: str) -> list[float]:
    """A deterministic word-overlap vector. Same text -> same vector;
    shared words -> nearby vectors. Free, offline, instant."""
    vector = [0.0] * settings.embedding_dimensions
    for word in text.lower().split():
        digest = hashlib.sha256(word.encode()).digest()
        slot = int.from_bytes(digest[:4], "big") % settings.embedding_dimensions
        vector[slot] += 1.0
    length = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / length for value in vector]


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts, recording the call like any other AI call.

    Batching matters: one call for a hundred texts costs the same tokens
    as a hundred calls for one text each, but is far faster and records
    one clean row instead of a hundred.
    """
    if not texts:
        return []

    from app.safety import ensure_budget_available

    await ensure_budget_available()  # embeddings cost money too — same stop
    started = time.perf_counter()
    model = "fake" if settings.fake_ai else settings.embedding_model

    try:
        if settings.fake_ai:
            vectors = [fake_embedding(text) for text in texts]
            input_tokens = sum(len(text) for text in texts) // 4
        else:
            client = AsyncOpenAI(api_key=settings.openai_api_key)
            response = await client.embeddings.create(
                model=settings.embedding_model, input=texts
            )
            vectors = [item.embedding for item in response.data]
            input_tokens = response.usage.total_tokens
    except Exception as error:
        await record_run(
            agent="embedder",
            model=model,
            latency_ms=int((time.perf_counter() - started) * 1000),
            input_tokens=0,
            output_tokens=0,
            cost_usd=0.0,
            success=False,
            error=f"{type(error).__name__}: {error}",
        )
        raise

    await record_run(
        agent="embedder",
        model=model,
        latency_ms=int((time.perf_counter() - started) * 1000),
        input_tokens=input_tokens,
        output_tokens=0,
        cost_usd=estimate_cost_usd(model, input_tokens, 0),
        success=True,
        error=None,
    )
    return vectors
