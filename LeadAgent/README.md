# LeadAgent

AI agent that handles inbound leads end-to-end: greets prospects, answers questions
from a RAG knowledge base, qualifies, books meetings on your real calendar, and
captures leads to your CRM. Everything grounded, logged, and evaluated.

## Quick start

### Prerequisites

- Docker Desktop
- Python 3.11+
- API keys: DeepSeek (agent LLM), Gemini (embeddings)

### Setup

```bash
# 1. Clone and install
git clone <repo>
cd LeadAgent
pip install -e ".[dev]"

# 2. Configure
cp .env.example .env
# Edit .env — fill in DEEPSEEK_API_KEY, GEMINI_API_KEY, and DATABASE_URL

# 3. Start Postgres + apply migrations
make up
make migrate

# 4. Ingest your business site
make dry-run URL=https://yoursite.com   # verify content extraction
make ingest URL=https://yoursite.com

# 5. Run tests
make test

# 6. Start the API
make api

# 7. Open the demo page
# → http://localhost:8000/widget/demo.html
```

## Embedding the widget

Add this script tag to any page:

```html
<script
  src="https://your-host/widget/widget.js"
  data-api="https://your-host"
  data-title="Chat with us"
  data-color="#2563eb">
</script>
```

| Attribute | Default | Description |
|---|---|---|
| `data-api` | (required) | API server URL |
| `data-title` | "Chat with us" | Header text |
| `data-color` | `#2563eb` | Brand color (hex) |
| `data-position` | `right` | Bubble position: `left` or `right` |

The widget injects a chat bubble and panel. Mobile-responsive. No secrets in the
widget — the LLM key stays server-side.

## Deploy with Docker Compose

```bash
# Full stack: postgres + API (serves widget)
docker compose up -d

# Apply migrations inside the container
docker compose exec api python db/apply_migrations.py

# Ingest your site
docker compose exec api python scripts/ingest.py --url https://yoursite.com
```

The API runs on port 8000. Point your embed snippet to `https://your-host:8000`.

### Neon-compatible (serverless Postgres)

Set `DATABASE_URL` to your Neon connection string. Remove the `postgres` service
from `docker-compose.yml`. Everything else works the same.

## Environment variables

See `.env.example` for all variables. Key ones:

| Variable | Description |
|---|---|
| `DATABASE_URL` | Postgres connection string |
| `DEEPSEEK_API_KEY` | DeepSeek API key (agent LLM) |
| `GEMINI_API_KEY` | Google Gemini key (embeddings only) |
| `CALENDAR_ADAPTER` | `mock` or `google` |
| `CRM_ADAPTER` | `mock` or `sheets` (Google Sheets) |
| `ADMIN_API_KEY` | Required for `/admin/*` endpoints |
| `ALLOWED_ORIGINS` | CORS allowlist (comma-separated, `*` for dev) |
| `RATE_LIMIT_RPM` | Requests per minute per IP (default 30) |

## Makefile targets

| Target | Description |
|---|---|
| `make up` | Start postgres (docker compose) |
| `make down` | Stop postgres |
| `make migrate` | Apply pending SQL migrations |
| `make api` | Start the API server (port 8000, hot reload) |
| `make chat` | Interactive CLI chat (no API needed) |
| `make traces` | CLI trace viewer |
| `make ingest URL=...` | Full ingest: crawl, chunk, embed, store |
| `make dry-run URL=...` | Crawl + chunk only, verify extraction |
| `make check-retrieval` | Run test questions, print recall@3 |
| `make test` | All tests (excludes live) |
| `make test-live` | Live integration tests (hits real APIs) |
| `make eval` | Full eval with LLM judge |
| `make eval-ci` | Deterministic assertions only (no API cost) |

## Architecture

```
domain/        Pydantic models — zero I/O
rag/           Crawl → chunk → embed → hybrid retrieval (RRF)
agent/         Conversation loop, tools, prompts, guardrails
integrations/  Calendar + CRM adapters (mock + real)
observability/ Turn-level trace logging
evals/         Eval datasets, LLM-as-judge grader
api/           FastAPI: POST /chat (SSE), admin trace endpoints
web/           Embeddable chat widget (vanilla JS)
db/            SQL migrations + custom runner
scripts/       CLI tools: chat, ingest, traces, API runner
tests/         pytest unit + integration + API tests
```

See `CLAUDE.md` for full codebase context. See `DECISIONS.md` for architectural
choices. See `TODO.md` for deferred work.
