.PHONY: up down migrate ingest check-retrieval test test-unit test-integration \
        lint format typecheck clean eval

# ── Infrastructure ────────────────────────────────────────────────────────────
up:
	docker compose up -d
	@echo "Waiting for postgres..."
	@until docker compose exec postgres pg_isready -U leadagent -d leadagent > /dev/null 2>&1; do sleep 1; done
	@echo "Postgres ready."

down:
	docker compose down

# ── Database ──────────────────────────────────────────────────────────────────
migrate:
	python db/apply_migrations.py

# ── Data pipeline ─────────────────────────────────────────────────────────────
ingest:
	@test -n "$(URL)" || (echo "Usage: make ingest URL=https://example.com [DEPTH=2] [MAX_PAGES=200]"; exit 1)
	python scripts/ingest.py --url "$(URL)" --depth $(or $(DEPTH),2) --max-pages $(or $(MAX_PAGES),200)

dry-run:
	@test -n "$(URL)" || (echo "Usage: make dry-run URL=https://example.com"; exit 1)
	python scripts/ingest.py --url "$(URL)" --depth $(or $(DEPTH),2) --dry-run

chat:
	python scripts/chat.py

traces:
	python scripts/traces.py

# ── Quality check ─────────────────────────────────────────────────────────────
check-retrieval:
	python checks/check_retrieval.py

# ── Testing ───────────────────────────────────────────────────────────────────
test:
	pytest tests/ -v --cov=rag --cov=domain --cov-report=term-missing

test-unit:
	pytest tests/ -v -m "not integration"

test-integration:
	pytest tests/ -v -m integration

# Full eval: runs all scenarios against the live model + LLM judge (costs money)
# Requires billing-enabled GEMINI_API_KEY
eval:
	python evals/runner.py

# Deterministic assertions only — no LLM judge, no API calls (safe for CI)
eval-ci:
	python evals/runner.py --skip-judge

# ── Code quality ──────────────────────────────────────────────────────────────
lint:
	ruff check .

format:
	ruff format .

typecheck:
	mypy rag/ domain/ --strict

# ── Utility ───────────────────────────────────────────────────────────────────
clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
