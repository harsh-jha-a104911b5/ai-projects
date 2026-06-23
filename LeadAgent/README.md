# LeadAgent

AI agent that handles inbound leads end-to-end. Grounded answers from your knowledge
base. Real calendar bookings. Everything logged and evaluated.

## Quick start (M1 — RAG pipeline)

### Prerequisites

- Docker Desktop
- Python 3.11+
- OpenAI API key

### Setup

```bash
# 1. Clone and install
git clone <repo>
cd LeadAgent
pip install -e ".[dev]"   # or: pip install -e . && pip install ruff pytest ...

# 2. Configure
cp .env.example .env
# Edit .env — fill in OPENAI_API_KEY and DATABASE_URL

# 3. Start Postgres (pgvector image — do not substitute postgres:16)
make up

# 4. Apply migrations
make migrate

# 5. Ingest a business site
make dry-run URL=https://yoursite.com   # verify trafilatura extracts content
make ingest URL=https://yoursite.com

# 6. Check retrieval quality
make check-retrieval

# 7. Run tests
make test
```

### Makefile targets

| Target | Description |
|---|---|
| `make up` | Start postgres (docker compose) |
| `make down` | Stop postgres |
| `make migrate` | Apply pending SQL migrations |
| `make dry-run URL=...` | Crawl + chunk, no embed/store — verify extraction |
| `make ingest URL=...` | Full ingest: crawl → chunk → embed → store |
| `make check-retrieval` | Run 10 test questions, print recall@3 table |
| `make test` | Run all tests with coverage |
| `make test-unit` | Unit tests only (no postgres required) |
| `make test-integration` | Integration tests (requires postgres) |
| `make lint` | ruff check |
| `make format` | ruff format |
| `make typecheck` | mypy strict |

## Architecture

See `CLAUDE.md` for full codebase context. See `DECISIONS.md` for architectural choices.
See `TODO.md` for deferred work.

```
domain/        Pydantic models — zero I/O
rag/           Crawl → chunk → embed → hybrid retrieval
agent/         Conversation loop + tools (M2+)
integrations/  Calendar + CRM adapters, mocked (M2+)
observability/ Structured logging (M5+)
evals/         Eval harness (M4+)
api/           FastAPI routes (M2+)
web/           Embeddable widget (M6+)
db/            SQL migrations + runner
scripts/       Operational scripts
checks/        Manual quality checks
tests/         pytest unit + integration
```

## Milestones

1. **M1 (current)** — Ingestion + hybrid retrieval
2. **M2** — Agent loop + tools (search, availability, booking)
3. **M3** — Guardrails + grounding enforcement
4. **M4** — Eval harness (automated grading, CI)
5. **M5** — Observability + real calendar/CRM integrations
6. **M6** — Embeddable widget + packaging
