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
