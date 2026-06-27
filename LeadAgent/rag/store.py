"""Persist document chunks to Postgres. Idempotent upsert on (source_url, chunk_index)."""

from __future__ import annotations

import json
import os

import psycopg
import structlog

from domain.chunk import DocumentChunk

logger = structlog.get_logger(__name__)


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    return url


async def upsert_chunks(
    chunks: list[DocumentChunk],
    embeddings: list[list[float]],
) -> None:
    """Insert or update chunks. Re-running with the same (source_url, chunk_index) overwrites content and embedding."""
    if len(chunks) != len(embeddings):
        raise ValueError(f"chunks ({len(chunks)}) and embeddings ({len(embeddings)}) length mismatch")

    if not chunks:
        return

    aconn = await psycopg.AsyncConnection.connect(
        _database_url(), autocommit=False
    )
    async with aconn:
        async with aconn.cursor() as cur:
            for chunk, embedding in zip(chunks, embeddings):
                await cur.execute(
                    """
                    INSERT INTO document_chunks
                        (content, embedding, source_url, chunk_index, metadata)
                    VALUES (%s, %s::vector, %s, %s, %s)
                    ON CONFLICT (source_url, chunk_index)
                    DO UPDATE SET
                        content   = EXCLUDED.content,
                        embedding = EXCLUDED.embedding,
                        metadata  = EXCLUDED.metadata
                    """,
                    (
                        chunk.content,
                        str(embedding),          # psycopg3 passes as text; pgvector casts
                        chunk.source_url,
                        chunk.chunk_index,
                        json.dumps(chunk.metadata.model_dump(mode="json")),
                    ),
                )

        await aconn.commit()

    logger.info("upserted_chunks", count=len(chunks))


async def delete_chunks_for_url(source_url: str) -> int:
    """Remove all chunks for a given source URL. Returns deleted row count."""
    aconn = await psycopg.AsyncConnection.connect(_database_url(), autocommit=False)
    async with aconn:
        async with aconn.cursor() as cur:
            await cur.execute(
                "DELETE FROM document_chunks WHERE source_url = %s",
                (source_url,),
            )
            deleted = cur.rowcount or 0
        await aconn.commit()

    logger.info("deleted_chunks", source_url=source_url, count=deleted)
    return deleted
