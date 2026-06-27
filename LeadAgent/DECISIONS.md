# DECISIONS.md

Running log of meaningful architectural choices. Add an entry whenever a non-obvious
decision is made. Include date, context, choice, and tradeoffs.

---

## 2026-06-15 — Migration runner: custom script over Alembic

**Context:** Need DB schema management without an ORM.
**Decision:** Custom `db/apply_migrations.py` that tracks applied migrations in a
`_schema_migrations` table. Files run in sorted filename order.
**Why:** Alembic couples naturally to SQLAlchemy. Without an ORM, using Alembic means
carrying its full abstraction layer for no benefit. The custom runner is ~60 lines and
does exactly what's needed.
**Tradeoff:** No autogenerate, no downgrade path. If schema stabilizes in M3+, revisit.

---

## 2026-06-15 — Vector search: no index in M1, exact scan

**Context:** M1 corpus is one small business site (~1k–5k chunks max).
**Decision:** No IVFFlat or HNSW index. Postgres does an exact sequential scan using
`ORDER BY embedding <=> query_embedding`. Correct and fast at this scale.
**Tradeoff:** At 100k+ chunks, exact scan becomes slow. Add HNSW at that point (better
than IVFFlat for ongoing inserts). Deferred to TODO.md.

---

## 2026-06-15 — FTS query: websearch_to_tsquery over plainto_tsquery / raw cast

**Context:** User queries are natural language ("how much does it cost?").
**Decision:** Use `websearch_to_tsquery('english', query)` in FTS lane.
**Why:** Raw `::tsquery` cast fails on punctuation (?, !, &). `plainto_tsquery` is safer
but doesn't support phrase queries. `websearch_to_tsquery` handles all natural language
input gracefully and is the correct function for user-facing search.
**Tradeoff:** None — this is strictly better for user input.

---

## 2026-06-15 — Rank fusion: RRF (k=60) over weighted sum

**Context:** Combining cosine similarity scores with BM25-style ts_rank_cd scores.
**Decision:** Reciprocal Rank Fusion using rank positions only. k=60 is the standard
default from the original RRF paper (Cormack et al., 2009).
**Why:** The two score distributions are incompatible scales. Any weight in a sum is
arbitrary and corpus-specific. RRF sidesteps this entirely.
**Tradeoff:** Discards raw cosine score from final ranking. `cosine_score` is still
returned in results so callers can apply post-hoc thresholds.

---

## 2026-06-15 — Crawler: trafilatura over Playwright for M1

**Context:** Need to extract clean text from the target business site.
**Decision:** httpx + trafilatura for static HTML extraction.
**Why:** Trafilatura is purpose-built for article/web content, removes boilerplate well,
no browser dependency. Fast and simple.
**Tradeoff:** Will not work on JavaScript-rendered SPAs. If target site is a React/Vue
SPA, trafilatura returns empty content. Mitigation: `--dry-run` flag checks extraction
quality before committing to a full ingest. Playwright deferred to TODO.md.

---

## 2026-06-15 — Target site: static HTML, Playwright not needed

**Context:** Dry-run against `https://studio--llc-canvas-86094581-ce999.us-central1.hosted.app/`
confirmed trafilatura extracts real content. The site is **MAC TechWorks & Consulting LLC**,
an executive operations consultancy.
**Result:** 3 pages crawled, 5 chunks produced, 0 empty pages. Static HTML.
**Decision:** Proceed without Playwright. Update `retrieval_questions.yaml` after first
full ingest to match this business's actual content.

---

## 2026-06-15 — Chunking: fixed sliding window (512t / 64t overlap) over semantic chunking

**Context:** Need to split crawled text into embeddable chunks.
**Decision:** tiktoken `cl100k_base`, 512-token window, 64-token overlap, with
sentence-boundary snapping (walk back ≤30 tokens to nearest `.!?\n`).
**Why:** Deterministic, fast, matches `text-embedding-3-small`'s sweet spot. Semantic
chunking (split on embedding distance drops) is slower, non-deterministic, and shows
marginal gains on short marketing-style business sites.
**Tradeoff:** May split mid-topic on long documents. The 64-token overlap mitigates this.
Revisit if M4 evals show poor retrieval recall.

---

## 2026-06-19 — M1 fix: URL canonicalization in crawler

**Context:** `tof.io/` and `tof.io/index.html` were ingested as separate pages — the
homepage was stored twice as distinct `source_url` values.
**Decision:** Extended `_normalize_url` to (a) collapse `/index.html` and `/index.htm`
to the parent directory, (b) lowercase the host, and (c) strip query strings.
**Why:** These URL variants are semantically identical pages. Counting them separately
inflates chunk counts and causes dedup to miss collisions.

---

## 2026-06-19 — Agent loop LLM: Gemini (same API key) over Anthropic

**Context:** Agent needs a tool-calling-capable LLM. Project already has `GEMINI_API_KEY`
for embeddings. The master prompt specified no new API keys.
**Decision:** Use `google-genai` SDK (already a dependency) with `gemini-2.0-flash` as
the default `AGENT_MODEL`. Tool-calling is via `genai_types.Tool` / `FunctionDeclaration`.
**Why:** Zero new dependencies, zero new credentials. `gemini-2.0-flash` is fast, cheap,
and supports parallel function calling.
**Tradeoff:** The embedding model (`gemini-embedding-001`) and agent model share the
same API key and project quota. On the free tier, `generate_content` and `embed_content`
have separate quota buckets so they don't compete, but a paid project should watch combined
usage. `anthropic` SDK stays in pyproject.toml as a future option.

---

## 2026-06-19 — Agent loop: bounded tool rounds, ToolSession per-conversation guardrail

**Context:** Need to prevent runaway loops and fabricated booking confirmations.
**Decision:** `AgentLoop` caps tool rounds at `AGENT_MAX_TOOL_ROUNDS` (default 8). A
single `ToolSession` is created in `AgentLoop.__init__` (one per conversation) and reused
across all `turn()` calls. `book_meeting` rejects any `slot_id` not in
`session.offered_slot_ids`. `capture_lead` writes via `CRMAdapter`. `escalate_to_human`
records an escalation ID and returns a structured handoff message.
**Why:** Per-conversation session means slots offered in turn N are still bookable in turn
N+2, which is the natural UX (prospect says "I'll take the Tuesday slot" in a later turn).
Isolation between conversations is by construction (each `AgentLoop` instance has its own
`ToolSession`). The slot guardrail and capture_lead are enforced in the dispatch layer, not
only in the prompt.

---

## 2026-06-20 — M3: grounded-or-escalate + capture_lead + escalate_to_human

**Context:** Pure prompt instruction is insufficient to prevent hallucinated answers.
**Decision:** `search_knowledge` now returns `grounded: false` plus a `grounding_note`
telling the model to escalate when no KB results are found. Two new tools added:
`capture_lead` (structured Pydantic-validated lead via CRMAdapter) and `escalate_to_human`
(records an EscalationRecord + returns a user-facing handoff message). System prompt
upgraded to v2 with explicit grounded-or-escalate, qualify→capture→book flow.
**Why:** Code-enforced guardrails at the dispatch layer are more reliable than prompt-only
instructions. The model still decides when to call escalate_to_human, but receives an
explicit machine-readable signal (`grounded: false`) rather than relying on self-awareness.
**Tradeoff:** A model that ignores `grounded: false` can still answer from parametric
knowledge. Full post-response grounding enforcement (checking that every factual claim
appeared in a retrieved chunk) requires an LLM judge → deferred to M4 evals.

---

## 2026-06-20 — M4: eval harness design choices

**Context:** Need measurable, reproducible grounding quality signal.
**Decision:** Scripted user turns (deterministic YAML scenarios) not a stochastic user-simulator.
Two-tier grading: deterministic assertions (booking guardrail, escalation fired/not, tools called,
lead captured) + LLM-as-judge Gemini for qualitative dims (groundedness, tone, qualifying, escalation).
Assertions run in CI (`make eval-ci`). Full eval + judge is on-demand/nightly (`make eval`).
**Why:** Deterministic inputs → deterministic assertions → no model variance in CI. LLM judge is
only needed for qualitative scores; those vary by model run and cost money.
**Grounding threshold tuning:** `GROUNDING_COSINE_THRESHOLD` env var (default 0.0 = off).
The eval captures `top_cosine_score` for every search_knowledge call, so we can see the score
distribution for KB-present vs KB-absent queries and pick a threshold that separates them.
`search_knowledge` returns `grounded=false` when threshold > 0.0 and top cosine is below it.

---

## 2026-06-23 — Agent LLM switched from Gemini to DeepSeek (OpenAI-compatible)

**Context:** Gemini free-tier quota for `generate_content` was exhausted and prepaid
credits depleted; embeddings (separate quota, `embed_content`) continued to work.
**Decision:** Switch agent loop and eval judge to DeepSeek via OpenAI SDK
(`base_url="https://api.deepseek.com"`, model `deepseek-chat`). Gemini key retained
exclusively for `gemini-embedding-001` embeddings.
**Changes:**
- `pyproject.toml`: `openai>=1.35.0` replaces `anthropic>=0.29.0`; `google-genai` stays
  for embeddings.
- `agent/tools.py`: replaced `genai_types.FunctionDeclaration`/`Tool` with plain JSON
  schema dicts (`TOOL_SPEC = [{"type":"function","function":{...}}]`).
- `agent/loop.py`: replaced `genai.Client` with `openai.AsyncOpenAI`, history is now
  `list[dict]` (OpenAI message format), tool results sent as `role="tool"` messages.
- `evals/judge.py`: replaced `genai.Client` with `openai.AsyncOpenAI` + DeepSeek base URL.
- `tests/test_agent_loop.py`: mock updated from Gemini Content objects to OpenAI
  `choices[0].message.tool_calls` / `.content` shape.
**Result:** All 87 tests pass (82 pass, 5 skipped for Docker). Live sign-off (`make chat`,
`make eval`) pending.

---

## 2026-06-24 — M5: turn-level logging via Postgres traces table

**Context:** Need observability into agent conversations for debugging and auditing.
**Decision:** Log every agent turn to the existing `traces` table: user message,
assistant response, tool calls (JSONB), retrieval chunks, latency. New migration
0003 adds `user_message`, `assistant_message`, `tool_calls` columns.
**Design:** Best-effort logging — failures are caught and logged, never crash the
agent. `DATABASE_URL` not set → logging silently skipped (tests, CI). CLI viewer
via `scripts/traces.py` (also `make traces`).

---

## 2026-06-24 — M5: Google Calendar adapter behind CalendarAdapter protocol

**Context:** MockCalendarAdapter works for tests but M5 requires a real booking.
**Decision:** `GoogleCalendarAdapter` using GCP service account credentials + httpx
calls to Calendar API v3. No new dependencies (`google-auth` is already a transitive
dep of `google-genai`, and `httpx` is in deps).
**Selection:** `CALENDAR_ADAPTER=google` in env; default `mock` keeps test/CI green.
**Tradeoff:** Service account requires calendar sharing setup. Alternative was
Cal.com (simpler API key auth) but user chose Google Calendar.

---

## 2026-06-24 — M6: Google Sheets as CRM via Sheets API v4

**Context:** `capture_lead` was still hitting MockCRMAdapter. User doesn't have a
HubSpot/GoHighLevel account. Google infra is already set up (service account + httpx).
**Decision:** `GoogleSheetsCRMAdapter` appends lead rows to a Google Sheet. Same
pattern as the calendar adapter: service account auth, httpx REST calls, env-selected.
Auto-creates header row on first write.
**Selection:** `CRM_ADAPTER=sheets` in env; default `mock` keeps test/CI green.
**Tradeoff:** Not a real CRM (no pipeline, no automation). Sufficient for lead
capture and handoff; HubSpot adapter can be added later behind the same protocol.

---

## 2026-06-24 — M6: live test gating

**Context:** GoogleCalendarAdapter and GoogleSheetsCRMAdapter hit real external APIs.
They must not run in CI or default `make test` (no credentials, would fail or spam).
**Decision:** `@pytest.mark.live` marker. `make test` excludes `-m "not live"`.
`make test-live` runs them explicitly. The 90 mock tests stay the default suite.

---

## 2026-06-24 — M6: SSE-streamed chat API with abuse protection

**Context:** LeadAgent needs a public endpoint for the embeddable widget. Public
endpoints on the open internet are an abuse surface (anyone can burn LLM tokens).
**Decision:** FastAPI `POST /chat` returns SSE stream (`text/event-stream`).
Token-by-token streaming via OpenAI SDK `stream=True`. Admin endpoints (`/admin/traces`)
gated behind `X-Admin-Key` header. Abuse protection: sliding-window per-IP rate
limiting (in-memory), max message length, max conversation turns, CORS origin allowlist.
All limits configurable via env vars.
**Design:** In-memory session store (dict of conversation_id → AgentLoop + history).
LLM key stays server-side — widget never sees it. On Windows, `SelectorEventLoop`
must be set before uvicorn starts (runner script `scripts/run_api.py`).
**Tradeoff:** In-memory rate limiter and session store only work for single-instance
deployment. Multi-instance would need Redis or similar. Fine for v1 (one deployment =
one business).

---

## 2026-06-24 — M6: Embeddable widget as self-contained JS

**Context:** Need a one-line embed for business websites.
**Decision:** Single `widget.js` file with embedded CSS. Configurable via data
attributes (`data-api`, `data-title`, `data-color`, `data-position`). Vanilla JS,
no framework, no build step. Served as static file by FastAPI (`/widget/widget.js`).
**Tradeoff:** No React/framework means less composability, but zero bundle size
overhead and no build toolchain. Sufficient for a chat bubble + panel.

---

## 2026-06-24 — Pre-pilot security hardening

**Context:** Product is now public-facing, collecting real PII. Security bar raised.
**Decisions (Tier 1 — breach/leak):**
- Security headers middleware: HSTS (behind FORCE_HTTPS), X-Content-Type-Options,
  X-Frame-Options, Referrer-Policy, Permissions-Policy.
- Admin auth: `secrets.compare_digest` (constant-time), audit logging on every access,
  PII redaction available via `?redact=true` on trace endpoints.
- Widget XSS: verified all user/model content uses `textContent` — innerHTML only for
  initial hardcoded DOM setup. Test asserts this.
- SQL: confirmed all 12 execute() paths use parameterized queries.
- Error sanitization: generic 500 handler, no stack traces in responses.

**Decisions (Tier 2 — LLM abuse):**
- Prompt injection defense: security rules in system prompt; KB content delimited with
  `[KB_DATA_START]...[KB_DATA_END]` markers; strict Pydantic validation on all tool args
  (length limits, slot_id pattern `[\w-]+`).
- Security evals: 8 scenarios (prompt extraction, grounding bypass, slot injection, data
  exfiltration, API key extraction, role override).
- Cost ceiling: per-conversation token budget (50k default) + daily ceiling (500k), both
  configurable. Token counting via tiktoken.
- Proxy-aware rate limiting: X-Forwarded-For with configurable trusted proxy IPs.

**Decisions (Data lifecycle):**
- `DELETE /admin/conversations/{id}` for GDPR/DPDP deletion requests.
- `POST /admin/purge?days=N` for retention TTL enforcement.
- Email adapter: SMTP + .ics, code-ready, pending app password setup.

---

## 2026-06-24 — Pre-pilot closeout: email provider, CRM decision, secret scanning

**Email provider: SendGrid over SMTP/Gmail App Password.**
A Gmail App Password is a broad credential that grants full account access — wrong
tool for transactional email. SendGrid API key is scoped to Mail Send only, revocable
independently, and supports SPF/DKIM/DMARC for deliverability. Uses httpx (already a
dep), no new packages. Status: code-ready, BLOCKED on SendGrid account + API key.

**v1 CRM: Google Sheets confirmed.**
User confirmed Sheets is acceptable for the pilot. Live write verified (`lead-f7cc8003`).
GHL/HubSpot deferred — not needed until a client requires it. Documented as a known
v1 limitation in README and TODO.
**Why:** User doesn't have GHL access. Sheets captures the same data (name, email,
phone, company, use case, budget, timeline) and is sufficient to demonstrate the
lead-capture flow to pilot prospects.

**Secret scanning: gitleaks in CI.**
GitHub Actions workflow added (`.github/workflows/ci.yml`) with gitleaks scanning
full git history on every push/PR. History scanned manually — no secrets found.
`SECURITY.md` documents all secret locations, scopes, and rotation procedures.

---

## 2026-06-25 — Deployment: Render + Neon + typed config

**Deploy platform: Render + Neon.**
Render for the web service (Docker, platform-managed TLS, free tier). Neon for
Postgres (pgvector support, free tier). Platform subdomain (`*.onrender.com`) for
now — custom domain can be added later.
**Why:** Fastest path to a live HTTPS URL with zero ops. Render auto-deploys from
GitHub push. Neon's free tier supports pgvector; Render's managed Postgres does not.

**Typed settings: pydantic-settings `Settings` class.**
Single typed config object (`config/__init__.py`) with all 40+ env vars documented,
validated, and grouped into client-specific vs infrastructure sections. Fail-fast
validation at startup in production (missing DEEPSEEK_API_KEY / GEMINI_API_KEY /
ADMIN_API_KEY → RuntimeError). Creates the seam for future per-client config
store without building multi-tenancy.

**GCP credentials: file path OR base64 JSON.**
Calendar and Sheets adapters now accept either a file path or base64-encoded JSON
for `GOOGLE_SERVICE_ACCOUNT_KEY`. Cloud platforms (Render, Railway) can't upload
files — base64 via env var is the standard workaround.

**Migrations on startup.**
`scripts/run_api.py` runs `db/apply_migrations.py` before starting uvicorn. Safe
for single-instance; would need a migration job for multi-instance.

**Embed snippet generator.**
`GET /embed-snippet` returns the configured `<script>` tag with the instance's URL
and branding. Demo page auto-detects the origin.
