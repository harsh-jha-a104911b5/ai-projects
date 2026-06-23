"""Domain models for document chunks and retrieval results. Zero I/O."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class ChunkMetadata(BaseModel):
    title: str | None = None
    crawled_at: datetime | None = None
    depth: int = 0
    word_count: int = 0
    extra: dict[str, str] = Field(default_factory=dict)


class DocumentChunk(BaseModel):
    """A chunk of text ready to embed and store. `id` is None before DB insert."""

    id: UUID | None = None
    content: str
    source_url: str
    chunk_index: int
    metadata: ChunkMetadata = Field(default_factory=ChunkMetadata)
    created_at: datetime | None = None


class RetrievedChunk(BaseModel):
    """A chunk returned by hybrid search, with fusion scores."""

    chunk_id: UUID
    content: str
    source_url: str
    chunk_index: int
    metadata: ChunkMetadata
    rrf_score: float
    cosine_score: float
    text_score: float
