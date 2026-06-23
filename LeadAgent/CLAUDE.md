# LeadAgent — Codebase Context for AI Sessions

## What this is

AI agent that handles inbound leads end-to-end: greets prospects, answers questions from
a RAG knowledge base, qualifies them, and books meetings / captures leads via real tool
calls. **Prime directive: production reliability.** Grounded or silent, no invented
commitments, everything logged and evaluated.

## Non-negotiables (read before touching anything)

1. **No ORM.** Raw SQL via psycopg3 (`psycopg[binary]`) only. No SQLAlchemy, no Tortoise.
2. **No LangChain**, no LlamaIndex, no heavy agent framework. Native SDK tool-calling only.
3. **No secrets in repo.** All credentials via env vars. `.env.example` is the contract.
4. **domain/ has zero I/O.** Only Pydantic models and pure business rules. No DB calls,
   no HTTP calls, no file I/O.
5. **Evals first.** Every behavior we care about has a test before the milestone is done.
6. **Ask before adding dependencies.** Any new package requires explicit approval.
7. **Simple > clever.** No premature abstractions. Three similar lines > one bad abstraction.

## Stack

- Python 3.11+, FastAPI, Pydantic v2
- PostgreSQL 16 + pgvector — single datastore, no Pinecone/Chroma
- psycopg3 (`psycopg[binary]`) — async-native, raw SQL
- Google Gemini `gemini-embedding-001` (768 dims, MRL-truncated + L2-normalised) for embeddings
  - Asymmetric task types: `RETRIEVAL_DOCUMENT` for stored chunks, `RETRIEVAL_QUERY` for search queries
- Anthropic Claude (native tool calling) for the agent loop (M2+)
- pytest + testcontainers for integration tests
- structlog for structured JSON logging

## Directory responsibilities

| Dir | Owns |
|---|---|
| `domain/` | Pydantic models, business rules — NO I/O |
| `rag/` | Crawl → chunk → embed → hybrid retrieval pipeline |
| `agent/` | Conversation loop, tool definitions, guardrails, prompt assembly (M2+) |
| `integrations/` | Calendar + CRM adapters, mock-first, behind interfaces (M2+) |
| `observability/` | Structured turn-level logging (M5+) |
| `evals/` | Eval datasets, LLM-as-judge grader, pytest entry (M4+) |
| `api/` | FastAPI routes: chat endpoint, trace view (M2+) |
| `web/` | Embeddable chat widget (M6+) |
| `db/` | SQL migrations + custom runner |
| `scripts/` | One-shot operational scripts (ingest, etc.) |
| `checks/` | Quality-check scripts (not CI tests — manual runs) |
| `tests/` | pytest unit + integration tests |

## Database

- **pgvector image:** always `pgvector/pgvector:pg16`. Stock `postgres:16` lacks the
  `vector` extension.
- **Migration runner:** `db/apply_migrations.py` — custom, no Alembic. Tracks applied
  files in `_schema_migrations` table. Idempotent. Run: `make migrate`.
- **Adding a migration:** create a new `db/migrations/NNNN_description.sql` file. The
  runner picks it up in alphabetical order. Never modify applied migrations.
- **CRITICAL:** `EMBEDDING_DIMENSIONS` in `.env` must match the `vector(N)` column
  definition. Changing either requires a new migration + full re-embed of all chunks.

## Retrieval

Hybrid search (vector + FTS) fused with RRF (Reciprocal Rank Fusion, k=60).
- Vector lane: exact cosine scan (`ORDER BY embedding <=>`) — no index needed for M1
  corpus size. Add HNSW/IVFFlat at 100k+ chunks.
- FTS lane: `websearch_to_tsquery('english', query)` — safe for raw user input.
  Never cast user text directly to `::tsquery`.
- Each lane retrieves `candidate_k=30` before fusion; RRF trims to `top_k`.
- The SQL lives in `rag/retriever.py`. Don't move it.

## How to run

```bash
# 1. Start postgres
make up

# 2. Apply migrations
make migrate

# 3. Ingest a site (dry-run first to verify content extraction)
make dry-run URL=https://example.com
make ingest URL=https://example.com

# 4. Check retrieval quality
make check-retrieval

# 5. Run tests
make test
```

## What NOT to build (v1 out-of-scope)

Multi-channel, analytics dashboards, multi-tenant/billing/auth, multiple CRMs/calendars,
fine-tuning, voice, reranking models. Ask before expanding scope.
