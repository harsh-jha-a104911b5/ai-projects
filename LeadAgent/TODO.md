# TODO.md — Deferred Work

Items explicitly out of scope for the current milestone. Pick up in the appropriate milestone.

**Current status: M4 complete, M5 in progress, M6 not started.**

---

## M5 — In progress

- [x] **Eval variance + hardening** — 3× variance stable (27-29/29), expanded to 29
  scenarios, code-level grounding backstop implemented and tested.
- [x] **Turn-level logging** — each turn logged to `traces` table with migration 0003.
- [x] **Trace view** — CLI via `make traces` / `scripts/traces.py`.
- [x] **Real calendar adapter** — GoogleCalendarAdapter implemented, env-selected
  (`CALENDAR_ADAPTER=google`). Needs GCP service account setup to test live.
- [ ] **Real CRM adapter** — deferred (user chose to skip for now).

## M6 — Not started

- [ ] **Embeddable widget** — React chat widget, script-tag drop-in, minimal CSS.
- [ ] **FastAPI chat endpoint** — public route `/chat` wired to AgentLoop.
- [ ] **docker-compose full-stack** — add API + widget services alongside postgres.
- [ ] **README** — complete setup guide with demo walkthrough.
- [ ] **CI pipeline** — GitHub Actions: lint + typecheck + test on PR.

---

## Retrieval / RAG

- [ ] **HNSW or IVFFlat vector index** — add when corpus exceeds 100k chunks. HNSW
  preferred for ongoing inserts. See DECISIONS.md 2026-06-15.
- [ ] **Playwright-based crawler** — for JS-rendered SPA sites where trafilatura returns
  empty content. Add as an optional crawler backend (`--renderer=playwright`).
- [ ] **Reranking model** — cross-encoder reranker as a post-RRF step. Revisit if evals
  show precision problems in M5+.
- [ ] **Multilingual support** — change tsvector config from `'english'` to `'simple'`
  or language-detected config if client site is multilingual.
- [ ] **Semantic chunking** — revisit if evals show poor retrieval recall.
- [ ] **Chunk metadata enrichment** — extract page title, section headings, structured
  data (FAQs, pricing tables) as additional metadata fields on chunks.

## Out of scope for v1 (do not build)

- Multi-channel (email, WhatsApp, voice)
- Analytics dashboards
- Multi-tenant / billing / auth beyond a basic admin key
- Multiple CRMs or calendars simultaneously
- Fine-tuning
