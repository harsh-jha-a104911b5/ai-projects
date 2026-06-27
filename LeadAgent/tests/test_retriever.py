"""Integration tests for the hybrid retriever.

Requires Docker (pgvector container via testcontainers fixture in conftest.py).
Run with: pytest tests/test_retriever.py -m integration
"""

from __future__ import annotations

import os
import pytest
import psycopg

from domain.chunk import ChunkMetadata, DocumentChunk, RetrievedChunk
from rag.store import upsert_chunks

pytestmark = pytest.mark.integration

FAKE_EMBEDDING_DIM = 768


# ── Helpers ───────────────────────────────────────────────────────────────────

def _unit_embedding(index: int) -> list[float]:
    v = [0.0] * FAKE_EMBEDDING_DIM
    v[index % FAKE_EMBEDDING_DIM] = 1.0
    return v


def _make_chunk(content: str, source_url: str, index: int) -> DocumentChunk:
    return DocumentChunk(
        content=content,
        source_url=source_url,
        chunk_index=index,
        metadata=ChunkMetadata(word_count=len(content.split())),
    )


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def set_db_url(pg_with_schema: str, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", pg_with_schema)
    monkeypatch.setenv("GEMINI_API_KEY", "AIza-test-dummy")


@pytest.fixture()
async def seeded_db(pg_with_schema: str):
    """Insert known chunks, clean up after each test."""
    from uuid import uuid4
    source = f"https://example.com/{uuid4().hex}"
    chunks = [
        _make_chunk("We offer competitive pricing plans for small businesses.", source, 0),
        _make_chunk("Our customer support team is available 24/7 via email and phone.", source, 1),
        _make_chunk("The onboarding process takes approximately two weeks.", source, 2),
        _make_chunk("We serve clients across retail, healthcare, and finance sectors.", source, 3),
        _make_chunk("You can request a free demo on our website at any time.", source, 4),
    ]
    embeddings = [_unit_embedding(i) for i in range(len(chunks))]
    await upsert_chunks(chunks, embeddings)

    yield source, chunks

    aconn = await psycopg.AsyncConnection.connect(pg_with_schema)
    async with aconn:
        await aconn.execute("DELETE FROM document_chunks WHERE source_url = %s", (source,))
        await aconn.commit()


# ── Tests ─────────────────────────────────────────────────────────────────────

def _async_embed(result: list[list[float]]):
    """Return an async function that always produces `result`, accepting any args."""
    async def _mock(texts, **kwargs):
        return result
    return _mock


@pytest.mark.asyncio
async def test_search_returns_results(seeded_db, monkeypatch):
    source, _ = seeded_db
    monkeypatch.setattr("rag.retriever.embed_texts",
                        _async_embed([[1.0] + [0.0] * (FAKE_EMBEDDING_DIM - 1)]))
    from rag.retriever import search_knowledge

    results = await search_knowledge("pricing", top_k=5, url_filter=source)
    assert isinstance(results, list)
    assert len(results) >= 1
    assert all(isinstance(r, RetrievedChunk) for r in results)


@pytest.mark.asyncio
async def test_search_returns_at_most_top_k(seeded_db, monkeypatch):
    source, _ = seeded_db
    monkeypatch.setattr("rag.retriever.embed_texts", _async_embed([_unit_embedding(0)]))
    from rag.retriever import search_knowledge

    results = await search_knowledge("pricing", top_k=2, url_filter=source)
    assert len(results) <= 2


@pytest.mark.asyncio
async def test_search_results_have_required_fields(seeded_db, monkeypatch):
    source, _ = seeded_db
    monkeypatch.setattr("rag.retriever.embed_texts", _async_embed([_unit_embedding(0)]))
    from rag.retriever import search_knowledge

    results = await search_knowledge("support", top_k=3, url_filter=source)
    for r in results:
        assert r.chunk_id is not None
        assert r.content
        assert r.source_url == source
        assert isinstance(r.rrf_score, float)
        assert isinstance(r.cosine_score, float)
        assert isinstance(r.text_score, float)


@pytest.mark.asyncio
async def test_fts_lane_finds_keyword_match(seeded_db, monkeypatch):
    """FTS should surface 'demo' even if vector similarity is low."""
    source, _ = seeded_db
    # Embedding that points away from all seeded chunks; FTS lane must compensate
    monkeypatch.setattr("rag.retriever.embed_texts",
                        _async_embed([[0.0] * (FAKE_EMBEDDING_DIM - 1) + [1.0]]))
    from rag.retriever import search_knowledge

    results = await search_knowledge("free demo", top_k=5, url_filter=source)
    contents = [r.content for r in results]
    assert any("demo" in c.lower() for c in contents), (
        "FTS lane should have surfaced the 'demo' chunk"
    )


@pytest.mark.asyncio
async def test_upsert_is_idempotent(seeded_db, pg_with_schema: str):
    """Re-inserting the same (source_url, chunk_index) must update, not duplicate."""
    source, chunks = seeded_db
    original_chunk = chunks[0]
    updated_content = "UPDATED: We offer very competitive pricing."
    updated = DocumentChunk(
        content=updated_content,
        source_url=original_chunk.source_url,
        chunk_index=original_chunk.chunk_index,
        metadata=original_chunk.metadata,
    )
    await upsert_chunks([updated], [_unit_embedding(0)])

    aconn = await psycopg.AsyncConnection.connect(pg_with_schema)
    async with aconn:
        async with aconn.cursor() as cur:
            await cur.execute(
                "SELECT content FROM document_chunks WHERE source_url = %s AND chunk_index = %s",
                (source, 0),
            )
            rows = await cur.fetchall()

    assert len(rows) == 1, f"Expected 1 row after upsert, got {len(rows)}"
    assert rows[0][0] == updated_content
