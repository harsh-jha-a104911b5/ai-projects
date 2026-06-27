-- pgvector extension (requires pgvector/pgvector:pg16 image)
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE document_chunks (
    id            UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    content       TEXT         NOT NULL,
    embedding     vector(768) NOT NULL,
    source_url    TEXT         NOT NULL,
    chunk_index   INTEGER      NOT NULL,
    metadata      JSONB        NOT NULL DEFAULT '{}',
    -- populated automatically by trigger below; never set from application code
    content_tsv   TSVECTOR,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),

    CONSTRAINT uq_chunks_url_index UNIQUE (source_url, chunk_index)
);

-- GIN index for full-text search
CREATE INDEX ix_chunks_tsv ON document_chunks USING gin(content_tsv);

-- Source URL index for re-ingestion invalidation
CREATE INDEX ix_chunks_source_url ON document_chunks (source_url);

-- No vector index in M1. Exact cosine scan is correct for < 10k chunks.
-- Add HNSW at 100k+ chunks. See DECISIONS.md and TODO.md.

-- Trigger: auto-populate tsvector column on insert or content update.
-- 'english' config handles stop words + stemming. See DECISIONS.md for multilingual note.
CREATE OR REPLACE FUNCTION chunks_tsv_update() RETURNS trigger AS $$
BEGIN
    NEW.content_tsv := to_tsvector('english', NEW.content);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_chunks_tsv_update
    BEFORE INSERT OR UPDATE OF content ON document_chunks
    FOR EACH ROW EXECUTE FUNCTION chunks_tsv_update();
