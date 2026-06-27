"""Hybrid retrieval: vector cosine similarity + Postgres FTS fused with RRF.

See DECISIONS.md for the rationale behind RRF over weighted sum, websearch_to_tsquery
over plainto_tsquery, and the absence of a vector index in M1.
"""

from __future__ import annotations

import os

import psycopg
import psycopg.rows
import structlog

from domain.chunk import ChunkMetadata, RetrievedChunk
from rag.embedder import embed_texts

logger = structlog.get_logger(__name__)

_HYBRID_SQL = """
WITH vector_ranked AS (
    SELECT
        id,
        content,
        source_url,
        chunk_index,
        metadata,
        1 - (embedding <=> %(query_embedding)s::vector) AS cosine_score,
        ROW_NUMBER() OVER (ORDER BY embedding <=> %(query_embedding)s) AS vec_rank
    FROM document_chunks
    {url_filter}
    ORDER BY embedding <=> %(query_embedding)s
    LIMIT %(candidate_k)s
),
text_ranked AS (
    SELECT
        id,
        content,
        source_url,
        chunk_index,
        metadata,
        ts_rank_cd(content_tsv, websearch_to_tsquery('english', %(query_text)s)) AS text_score,
        ROW_NUMBER() OVER (
            ORDER BY ts_rank_cd(content_tsv, websearch_to_tsquery('english', %(query_text)s)) DESC
        ) AS text_rank
    FROM document_chunks
    WHERE content_tsv @@ websearch_to_tsquery('english', %(query_text)s)
    {url_filter2}
    ORDER BY text_score DESC
    LIMIT %(candidate_k)s
),
fused AS (
    SELECT
        COALESCE(v.id, t.id)                    AS chunk_id,
        COALESCE(v.content, t.content)           AS content,
        COALESCE(v.source_url, t.source_url)     AS source_url,
        COALESCE(v.chunk_index, t.chunk_index)   AS chunk_index,
        COALESCE(v.metadata, t.metadata)         AS metadata,
        COALESCE(1.0 / (%(rrf_k)s + v.vec_rank),  0.0)
        + COALESCE(1.0 / (%(rrf_k)s + t.text_rank), 0.0) AS rrf_score,
        COALESCE(v.cosine_score, 0.0)            AS cosine_score,
        COALESCE(t.text_score,  0.0)             AS text_score
    FROM vector_ranked v
    FULL OUTER JOIN text_ranked t ON v.id = t.id
)
SELECT chunk_id, content, source_url, chunk_index, metadata,
       rrf_score, cosine_score, text_score
FROM fused
WHERE cosine_score >= %(min_cosine_score)s OR cosine_score = 0.0
ORDER BY rrf_score DESC
LIMIT %(top_k)s
"""


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    return url


async def search_knowledge(
    query: str,
    *,
    top_k: int | None = None,
    candidate_k: int | None = None,
    rrf_k: int | None = None,
    min_cosine_score: float | None = None,
    url_filter: str | None = None,
) -> list[RetrievedChunk]:
    """Hybrid RAG retrieval. Returns up to `top_k` chunks ranked by RRF score."""
    top_k = top_k if top_k is not None else int(os.environ.get("RETRIEVAL_TOP_K", "5"))
    candidate_k = candidate_k if candidate_k is not None else int(os.environ.get("RETRIEVAL_CANDIDATE_K", "30"))
    rrf_k = rrf_k if rrf_k is not None else int(os.environ.get("RETRIEVAL_RRF_K", "60"))
    min_cosine_score = min_cosine_score if min_cosine_score is not None else float(os.environ.get("RETRIEVAL_MIN_COSINE_SCORE", "0.0"))

    # Embed the query with RETRIEVAL_QUERY task type for asymmetric retrieval
    embeddings = await embed_texts([query], task_type="RETRIEVAL_QUERY")
    query_embedding = embeddings[0]

    # Build optional per-lane WHERE clause for source_url domain filter
    filter_clause = "WHERE source_url LIKE %(url_pattern)s" if url_filter else ""
    filter_clause2 = "AND source_url LIKE %(url_pattern)s" if url_filter else ""
    sql = _HYBRID_SQL.format(url_filter=filter_clause, url_filter2=filter_clause2)

    params: dict[str, object] = {
        "query_embedding": str(query_embedding),
        "query_text": query,
        "candidate_k": candidate_k,
        "rrf_k": float(rrf_k),
        "min_cosine_score": min_cosine_score,
        "top_k": top_k,
    }
    if url_filter:
        params["url_pattern"] = f"%{url_filter}%"

    aconn = await psycopg.AsyncConnection.connect(
        _database_url(), row_factory=psycopg.rows.dict_row
    )
    async with aconn:
        async with aconn.cursor() as cur:
            await cur.execute(sql, params)
            rows = await cur.fetchall()

    results = []
    for row in rows:
        metadata = ChunkMetadata.model_validate(row["metadata"])
        results.append(
            RetrievedChunk(
                chunk_id=row["chunk_id"],
                content=row["content"],
                source_url=row["source_url"],
                chunk_index=row["chunk_index"],
                metadata=metadata,
                rrf_score=float(row["rrf_score"]),
                cosine_score=float(row["cosine_score"]),
                text_score=float(row["text_score"]),
            )
        )

    logger.info(
        "search_knowledge",
        query_preview=query[:80],
        results=len(results),
        top_k=top_k,
    )
    return results
