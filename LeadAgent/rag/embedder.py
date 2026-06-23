"""Embed text chunks using Google Gemini (gemini-embedding-001).

Uses asymmetric task types for retrieval quality:
  - RETRIEVAL_DOCUMENT  when storing chunks (called by ingest pipeline)
  - RETRIEVAL_QUERY     when embedding search queries (called by retriever)

Output dimensionality is 768 (MRL truncation of the full 3072-dim space).
Truncated MRL vectors must be L2-normalised before use with cosine similarity.

The SDK call is synchronous; all public functions run it via asyncio.to_thread.
"""

from __future__ import annotations

import asyncio
import math
import os

import structlog
from google import genai
from google.genai import types
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = structlog.get_logger(__name__)

EMBEDDING_MODEL = "gemini-embedding-001"

_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY is not set")
        _client = genai.Client(api_key=api_key)
    return _client


def _model() -> str:
    return os.environ.get("EMBEDDING_MODEL", EMBEDDING_MODEL)


def _dimensions() -> int:
    return int(os.environ.get("EMBEDDING_DIMENSIONS", "768"))


def _batch_size() -> int:
    return int(os.environ.get("EMBEDDING_BATCH_SIZE", "100"))


def _l2_normalize(v: list[float]) -> list[float]:
    """L2-normalize a vector. Required for MRL-truncated Gemini embeddings."""
    norm = math.sqrt(sum(x * x for x in v))
    if norm == 0.0:
        return v
    return [x / norm for x in v]


def _embed_batch_sync(
    texts: list[str],
    task_type: str,
) -> list[list[float]]:
    """Synchronous Gemini embed call. Run via asyncio.to_thread."""
    client = _get_client()
    model = _model()
    dims = _dimensions()

    result = client.models.embed_content(
        model=model,
        contents=texts,
        config=types.EmbedContentConfig(
            task_type=task_type,
            output_dimensionality=dims,
        ),
    )

    embeddings = [list(e.values) for e in result.embeddings]

    # MRL-truncated vectors are not unit-length; normalise so cosine similarity
    # works correctly via pgvector's <=> operator (which assumes normalised vectors).
    embeddings = [_l2_normalize(e) for e in embeddings]
    return embeddings


# Wrap the retry decorator around the sync function so tenacity can handle
# Gemini SDK exceptions (which are regular Python exceptions, not coroutines).
@retry(
    retry=retry_if_exception_type(Exception),
    wait=wait_exponential(multiplier=1, min=2, max=60),
    stop=stop_after_attempt(5),
    reraise=True,
)
def _embed_batch_sync_with_retry(
    texts: list[str],
    task_type: str,
) -> list[list[float]]:
    return _embed_batch_sync(texts, task_type)


async def embed_texts(
    texts: list[str],
    *,
    task_type: str = "RETRIEVAL_DOCUMENT",
) -> list[list[float]]:
    """Embed a list of texts. Returns embeddings in the same order as input.

    Use task_type="RETRIEVAL_DOCUMENT" for chunks to store (default).
    Use task_type="RETRIEVAL_QUERY"    for search queries.
    """
    if not texts:
        return []

    batch_size = _batch_size()
    model = _model()
    all_embeddings: list[list[float]] = []

    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        logger.info(
            "embedding_batch",
            model=model,
            task_type=task_type,
            batch_start=i,
            batch_size=len(batch),
            total=len(texts),
        )
        embeddings = await asyncio.to_thread(
            _embed_batch_sync_with_retry, batch, task_type
        )
        all_embeddings.extend(embeddings)

    return all_embeddings
